//! Shared business logic for the desktop app and the local MCP process.
use anyhow::{anyhow, bail, Context, Result};
use chrono::{DateTime, Duration, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use sqlx::{
    sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions},
    FromRow, SqliteConnection, SqlitePool,
};
use std::{
    path::{Path, PathBuf},
    time::Duration as StdDuration,
};

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct Task {
    pub id: i64,
    pub title: String,
    pub notes: Option<String>,
    pub due_at: Option<String>,
    pub reminder_at: Option<String>,
    pub priority: i64,  // 0 normal, 1 important, 2 urgent
    pub status: String, // open | done
    pub created_at: String,
    pub completed_at: Option<String>,
    pub notification_sent_at: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct NewTask {
    pub title: String,
    pub notes: Option<String>,
    /// RFC3339 including timezone, e.g. 2026-11-16T18:00:00+01:00.
    pub due_at: Option<String>,
    /// RFC3339 including timezone; defaults to 30 minutes before due_at.
    pub reminder_at: Option<String>,
    pub priority: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TaskPatch {
    pub title: Option<String>,
    pub notes: Option<String>,
    pub priority: Option<i64>,
}

#[derive(Clone)]
pub struct TaskStore {
    pool: SqlitePool,
}

pub fn default_db_path() -> Result<PathBuf> {
    if let Some(custom) = std::env::var_os("PERSONAL_ISLAND_DB") {
        return Ok(PathBuf::from(custom));
    }
    Ok(dirs::data_local_dir()
        .context("Unable to determine local data directory")?
        .join("PersonalIsland")
        .join("tasks.sqlite3"))
}

pub fn now_utc() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn as_utc(when: &str) -> Result<String> {
    let value = DateTime::parse_from_rfc3339(when)
        .with_context(|| format!("Invalid RFC3339 timestamp (timezone required): {when}"))?;
    Ok(value
        .with_timezone(&Utc)
        .to_rfc3339_opts(SecondsFormat::Secs, true))
}

fn validate_title(title: &str) -> Result<String> {
    let clean = title.trim();
    if clean.is_empty() || clean.chars().count() > 200 {
        bail!("Task title must contain 1 to 200 characters");
    }
    Ok(clean.to_owned())
}

fn validate_priority(priority: i64) -> Result<i64> {
    if !(0..=2).contains(&priority) {
        bail!("Priority must be 0 (normal), 1 (important) or 2 (urgent)");
    }
    Ok(priority)
}

#[derive(Serialize)]
struct PreparedTask {
    title: String,
    notes: Option<String>,
    due_at: Option<String>,
    reminder_at: Option<String>,
    priority: i64,
}
impl PreparedTask {
    fn new(input: NewTask) -> Result<Self> {
        let title = validate_title(&input.title)?;
        let priority = validate_priority(input.priority.unwrap_or(0))?;
        let notes = input.notes.filter(|v| !v.trim().is_empty());
        let due_at = input.due_at.as_deref().map(as_utc).transpose()?;
        let reminder_at = match (input.reminder_at.as_deref(), due_at.as_deref()) {
            (Some(reminder), _) => Some(as_utc(reminder)?),
            (None, Some(due)) => Some(
                (DateTime::parse_from_rfc3339(due)?.with_timezone(&Utc) - Duration::minutes(30))
                    .to_rfc3339_opts(SecondsFormat::Secs, true),
            ),
            (None, None) => None,
        };
        Ok(Self {
            title,
            notes,
            due_at,
            reminder_at,
            priority,
        })
    }
    async fn insert(&self, connection: &mut SqliteConnection) -> Result<Task> {
        Ok(sqlx::query_as::<_, Task>(
            "INSERT INTO tasks (title, notes, due_at, reminder_at, priority, created_at)
             VALUES (?, ?, ?, ?, ?, ?) RETURNING *",
        )
        .bind(&self.title)
        .bind(&self.notes)
        .bind(&self.due_at)
        .bind(&self.reminder_at)
        .bind(self.priority)
        .bind(now_utc())
        .fetch_one(connection)
        .await?)
    }
}

impl TaskStore {
    pub async fn open_default() -> Result<Self> {
        Self::open_at(default_db_path()?).await
    }

    pub async fn open_at(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("Could not create {parent:?}"))?;
        }
        let opts = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .busy_timeout(StdDuration::from_secs(5));
        let pool = SqlitePoolOptions::new()
            .max_connections(5)
            .connect_with(opts)
            .await?;
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                notes TEXT,
                due_at TEXT,
                reminder_at TEXT,
                priority INTEGER NOT NULL DEFAULT 0 CHECK(priority BETWEEN 0 AND 2),
                status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'done')),
                created_at TEXT NOT NULL,
                completed_at TEXT,
                notification_sent_at TEXT
            )",
        )
        .execute(&pool)
        .await?;
        sqlx::query("CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(status, due_at)")
            .execute(&pool)
            .await?;
        sqlx::query("CREATE INDEX IF NOT EXISTS idx_tasks_reminder ON tasks(status, reminder_at, notification_sent_at)")
            .execute(&pool).await?;
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS task_mcp_requests (
                request_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                task_ids TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )",
        )
        .execute(&pool)
        .await?;
        Ok(Self { pool })
    }

    pub async fn create(&self, input: NewTask) -> Result<Task> {
        let prepared = PreparedTask::new(input)?;
        let mut connection = self.pool.acquire().await?;
        prepared.insert(&mut connection).await
    }

    /// Atomically create 1..=50 tasks. A persistent request key makes retries safe.
    /// A reused key with changed input fails. Deleted tasks are never recreated.
    pub async fn create_many_once(
        &self,
        request_key: &str,
        inputs: Vec<NewTask>,
    ) -> Result<Vec<Task>> {
        if request_key.is_empty()
            || request_key.len() > 128
            || !request_key
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"-_:./".contains(&c))
        {
            bail!("request_key must contain 1 to 128 ASCII letters, digits or -_:./");
        }
        if inputs.is_empty() || inputs.len() > 50 {
            bail!("Create between 1 and 50 tasks per request");
        }
        let prepared = inputs
            .into_iter()
            .map(PreparedTask::new)
            .collect::<Result<Vec<_>>>()?;
        let payload = serde_json::to_string(&prepared)?;
        let mut tx = self.pool.begin().await?;
        // This first write serializes concurrent retries before reading a receipt.
        let inserted = sqlx::query("INSERT INTO task_mcp_requests (request_key, payload, created_at) VALUES (?, ?, ?) ON CONFLICT(request_key) DO NOTHING")
            .bind(request_key).bind(&payload).bind(now_utc()).execute(&mut *tx).await?.rows_affected();
        let tasks = if inserted == 0 {
            let (previous, ids): (String, String) = sqlx::query_as(
                "SELECT payload, task_ids FROM task_mcp_requests WHERE request_key = ?",
            )
            .bind(request_key)
            .fetch_one(&mut *tx)
            .await?;
            if previous != payload {
                bail!("request_key was already used with different task data; use a new key for a new request");
            }
            let mut tasks = Vec::new();
            for id in serde_json::from_str::<Vec<i64>>(&ids)? {
                tasks.push(sqlx::query_as::<_, Task>("SELECT * FROM tasks WHERE id = ?").bind(id)
                    .fetch_optional(&mut *tx).await?
                    .ok_or_else(|| anyhow!("Task #{id} from this request was deleted; it will not be recreated by a retry"))?);
            }
            tasks
        } else {
            let mut tasks = Vec::new();
            for input in prepared {
                tasks.push(input.insert(&mut tx).await?);
            }
            let ids = tasks.iter().map(|t| t.id).collect::<Vec<_>>();
            sqlx::query("UPDATE task_mcp_requests SET task_ids = ? WHERE request_key = ?")
                .bind(serde_json::to_string(&ids)?)
                .bind(request_key)
                .execute(&mut *tx)
                .await?;
            tasks
        };
        tx.commit().await?;
        Ok(tasks)
    }

    /// Deadlines in [start_at, end_at); this application does not store event durations.
    pub async fn schedule(
        &self,
        start_at: &str,
        end_at: &str,
        include_completed: bool,
    ) -> Result<Vec<Task>> {
        let start = as_utc(start_at)?;
        let end = as_utc(end_at)?;
        let duration = DateTime::parse_from_rfc3339(&end)? - DateTime::parse_from_rfc3339(&start)?;
        if duration <= Duration::zero() || duration > Duration::days(93) {
            bail!("Schedule range must be positive and no longer than 93 days");
        }
        Ok(sqlx::query_as::<_, Task>("SELECT * FROM tasks WHERE (? OR status = 'open') AND due_at >= ? AND due_at < ? ORDER BY due_at ASC, priority DESC, id ASC")
            .bind(include_completed).bind(start).bind(end).fetch_all(&self.pool).await?)
    }

    pub async fn list(&self, include_completed: bool) -> Result<Vec<Task>> {
        Ok(sqlx::query_as::<_, Task>(
            "SELECT * FROM tasks WHERE (? OR status = 'open')
             ORDER BY CASE WHEN status = 'done' THEN 1 ELSE 0 END,
                      CASE WHEN due_at IS NULL THEN 1 ELSE 0 END,
                      due_at ASC, priority DESC, created_at DESC",
        )
        .bind(include_completed)
        .fetch_all(&self.pool)
        .await?)
    }

    pub async fn get(&self, id: i64) -> Result<Task> {
        sqlx::query_as::<_, Task>("SELECT * FROM tasks WHERE id = ?")
            .bind(id)
            .fetch_optional(&self.pool)
            .await?
            .ok_or_else(|| anyhow!("Task #{id} not found"))
    }

    pub async fn set_complete(&self, id: i64, completed: bool) -> Result<Task> {
        let now = if completed { Some(now_utc()) } else { None };
        sqlx::query("UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?")
            .bind(if completed { "done" } else { "open" })
            .bind(now)
            .bind(id)
            .execute(&self.pool)
            .await?;
        self.get(id).await
    }

    pub async fn patch(&self, id: i64, patch: TaskPatch) -> Result<Task> {
        let current = self.get(id).await?;
        let title = match patch.title {
            Some(s) => validate_title(&s)?,
            None => current.title,
        };
        let priority = match patch.priority {
            Some(p) => validate_priority(p)?,
            None => current.priority,
        };
        let notes = patch.notes.or(current.notes);
        sqlx::query("UPDATE tasks SET title = ?, notes = ?, priority = ? WHERE id = ?")
            .bind(title)
            .bind(notes)
            .bind(priority)
            .bind(id)
            .execute(&self.pool)
            .await?;
        self.get(id).await
    }

    /// Reschedule and reset notification delivery. None clears a timestamp.
    /// When due_at is set and reminder_at is absent, 30m before due is used.
    pub async fn reschedule(
        &self,
        id: i64,
        due_at: Option<String>,
        reminder_at: Option<String>,
    ) -> Result<Task> {
        self.get(id).await?;
        let due_at = due_at.as_deref().map(as_utc).transpose()?;
        let reminder_at = match (reminder_at.as_deref(), due_at.as_deref()) {
            (Some(value), _) => Some(as_utc(value)?),
            (None, Some(due)) => Some(
                (DateTime::parse_from_rfc3339(due)?.with_timezone(&Utc) - Duration::minutes(30))
                    .to_rfc3339_opts(SecondsFormat::Secs, true),
            ),
            _ => None,
        };
        sqlx::query("UPDATE tasks SET due_at = ?, reminder_at = ?, notification_sent_at = NULL WHERE id = ?")
            .bind(due_at).bind(reminder_at).bind(id).execute(&self.pool).await?;
        self.get(id).await
    }

    pub async fn delete(&self, id: i64) -> Result<()> {
        let rows = sqlx::query("DELETE FROM tasks WHERE id = ?")
            .bind(id)
            .execute(&self.pool)
            .await?
            .rows_affected();
        if rows == 0 {
            bail!("Task #{id} not found");
        }
        Ok(())
    }

    pub async fn due_notifications(&self) -> Result<Vec<Task>> {
        self.due_notifications_since(None).await
    }

    /// Desktop startup handles older reminders in its recurring task review.
    /// Apply the cutoff before LIMIT so an old backlog cannot starve new alerts.
    pub async fn due_notifications_since(&self, since: Option<&str>) -> Result<Vec<Task>> {
        let since = since.map(as_utc).transpose()?;
        Ok(sqlx::query_as::<_, Task>(
            "SELECT * FROM tasks WHERE status = 'open' AND reminder_at IS NOT NULL
              AND reminder_at <= ? AND notification_sent_at IS NULL
              AND (? IS NULL OR reminder_at > ?)
              ORDER BY reminder_at ASC LIMIT 25",
        )
        .bind(now_utc())
        .bind(&since)
        .bind(&since)
        .fetch_all(&self.pool)
        .await?)
    }

    pub async fn mark_notified(&self, id: i64) -> Result<()> {
        sqlx::query("UPDATE tasks SET notification_sent_at = ? WHERE id = ? AND status = 'open'")
            .bind(now_utc())
            .bind(id)
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    /// Acknowledge the exact reminder rendered by the desktop. A delayed UI
    /// acknowledgement must not consume a newly rescheduled reminder.
    pub async fn mark_reminder_presented(&self, id: i64, reminder_at: &str) -> Result<bool> {
        let reminder_at = as_utc(reminder_at)?;
        Ok(sqlx::query("UPDATE tasks SET notification_sent_at = ? WHERE id = ? AND status = 'open' AND reminder_at = ? AND reminder_at <= ? AND notification_sent_at IS NULL")
            .bind(now_utc()).bind(id).bind(reminder_at).bind(now_utc())
            .execute(&self.pool).await?.rows_affected() == 1)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn bundled_sqlite_contains_the_wal_disclosure_fix() {
        let dir = tempfile::tempdir().unwrap();
        let store = TaskStore::open_at(dir.path().join("test.sqlite3"))
            .await
            .unwrap();
        let version: String = sqlx::query_scalar("SELECT sqlite_version()")
            .fetch_one(&store.pool)
            .await
            .unwrap();
        let parts: Vec<u32> = version
            .split('.')
            .map(|part| part.parse().unwrap())
            .collect();
        assert!(
            parts.as_slice() >= [3, 54, 0].as_slice(),
            "SQLite {version} is older than the WAL disclosure fix"
        );
    }

    #[tokio::test]
    async fn create_complete_reopen_and_reschedule() {
        let dir = tempfile::tempdir().unwrap();
        let store = TaskStore::open_at(dir.path().join("test.sqlite3"))
            .await
            .unwrap();
        let task = store
            .create(NewTask {
                title: "  Сделать MVP  ".to_string(),
                notes: None,
                due_at: Some("2030-01-02T17:00:00+03:00".into()),
                reminder_at: None,
                priority: Some(2),
            })
            .await
            .unwrap();
        assert_eq!(task.title, "Сделать MVP");
        assert_eq!(task.due_at.as_deref(), Some("2030-01-02T14:00:00Z"));
        assert_eq!(task.reminder_at.as_deref(), Some("2030-01-02T13:30:00Z"));
        assert_eq!(store.list(false).await.unwrap().len(), 1);
        store.set_complete(task.id, true).await.unwrap();
        assert!(store.list(false).await.unwrap().is_empty());
        store.set_complete(task.id, false).await.unwrap();
        store
            .reschedule(task.id, Some("2031-01-01T12:00:00Z".into()), None)
            .await
            .unwrap();
        assert_eq!(
            store.get(task.id).await.unwrap().due_at.as_deref(),
            Some("2031-01-01T12:00:00Z")
        );
    }

    #[tokio::test]
    async fn due_notifications_are_sent_once() {
        let dir = tempfile::tempdir().unwrap();
        let store = TaskStore::open_at(dir.path().join("test.sqlite3"))
            .await
            .unwrap();
        let t = store
            .create(NewTask {
                title: "Проверить уведомления".into(),
                notes: None,
                due_at: None,
                reminder_at: Some("2020-01-01T00:00:00Z".into()),
                priority: None,
            })
            .await
            .unwrap();
        assert_eq!(store.due_notifications().await.unwrap().len(), 1);
        store.mark_notified(t.id).await.unwrap();
        assert!(store.due_notifications().await.unwrap().is_empty());
    }

    #[tokio::test]
    async fn old_review_backlog_does_not_starve_new_alerts_or_mark_tasks_delivered() {
        let dir = tempfile::tempdir().unwrap();
        let store = TaskStore::open_at(dir.path().join("test.sqlite3"))
            .await
            .unwrap();
        for index in 0..26 {
            store
                .create(NewTask {
                    title: format!("Old {index}"),
                    notes: None,
                    due_at: None,
                    reminder_at: Some("2020-01-01T00:00:00Z".into()),
                    priority: None,
                })
                .await
                .unwrap();
        }
        let recent = store
            .create(NewTask {
                title: "Recent".into(),
                notes: None,
                due_at: None,
                reminder_at: Some("2021-01-01T00:00:00Z".into()),
                priority: None,
            })
            .await
            .unwrap();
        let pending = store
            .due_notifications_since(Some("2020-01-01T03:00:00+03:00"))
            .await
            .unwrap();
        assert_eq!(pending.len(), 1);
        assert_eq!(pending[0].id, recent.id);
        assert_eq!(store.due_notifications().await.unwrap().len(), 25);
        assert!(store
            .list(false)
            .await
            .unwrap()
            .iter()
            .all(|task| task.notification_sent_at.is_none()));
    }

    #[tokio::test]
    async fn reject_invalid_title() {
        let dir = tempfile::tempdir().unwrap();
        let store = TaskStore::open_at(dir.path().join("test.sqlite3"))
            .await
            .unwrap();
        assert!(store
            .create(NewTask {
                title: "  ".into(),
                notes: None,
                due_at: None,
                reminder_at: None,
                priority: None
            })
            .await
            .is_err());
    }
}

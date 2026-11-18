use serde::{Deserialize, Serialize};
use sqlx::{sqlite::SqliteConnectOptions, FromRow, SqlitePool};
use std::path::Path;

#[derive(Serialize, FromRow, Debug)]
pub struct Note {
    id: i64,
    category: String,
    title: String,
    document: String,
    revision: i64,
    updated_at: String,
}
#[derive(Deserialize)]
pub struct NoteInput {
    category: String,
    title: String,
    document: String,
}
pub struct NotesStore(SqlitePool);
impl NotesStore {
    pub async fn summary(&self) -> Result<(i64, i64, i64), String> {
        sqlx::query_as("SELECT COALESCE(SUM(category='notes'),0),COALESCE(SUM(category='ideas'),0),COALESCE(SUM(category='shopping'),0) FROM notes")
            .fetch_one(&self.0).await.map_err(|e|e.to_string())
    }
    pub async fn open(path: &Path) -> Result<Self, String> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(sqlx::sqlite::SqliteJournalMode::Wal)
            .busy_timeout(std::time::Duration::from_secs(3));
        let pool = sqlx::sqlite::SqlitePoolOptions::new()
            .max_connections(2)
            .connect_with(options)
            .await
            .map_err(|e| e.to_string())?;
        sqlx::query("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL, document TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")
            .execute(&pool).await.map_err(|e| e.to_string())?;
        Ok(Self(pool))
    }
    async fn list(&self) -> Result<Vec<Note>, String> {
        sqlx::query_as("SELECT * FROM notes ORDER BY updated_at DESC, id DESC")
            .fetch_all(&self.0)
            .await
            .map_err(|e| e.to_string())
    }
    async fn save(&self, id: Option<i64>, revision: i64, note: NoteInput) -> Result<Note, String> {
        if !["notes", "ideas", "shopping"].contains(&note.category.as_str()) {
            return Err("Неизвестный раздел заметок".into());
        }
        if note.title.chars().count() > 200 || note.document.len() > 256 * 1024 {
            return Err("Заметка слишком большая: максимум 256 КБ, название — 200 символов".into());
        }
        let doc: serde_json::Value = serde_json::from_str(&note.document)
            .map_err(|_| "Неверный формат заметки".to_string())?;
        if doc.get("type").and_then(|t| t.as_str()) != Some("doc") {
            return Err("Неверный формат заметки".into());
        }
        if let Some(id) = id {
            return sqlx::query_as("UPDATE notes SET category=?, title=?, document=?, revision=revision+1, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND revision=? RETURNING *")
                .bind(note.category).bind(note.title).bind(note.document).bind(id).bind(revision)
                .fetch_optional(&self.0).await.map_err(|e| e.to_string())?
                .ok_or_else(|| "Заметка уже изменена. Скопируй текст и открой её заново.".into());
        }
        sqlx::query_as("INSERT INTO notes(category,title,document) VALUES(?,?,?) RETURNING *")
            .bind(note.category)
            .bind(note.title)
            .bind(note.document)
            .fetch_one(&self.0)
            .await
            .map_err(|e| e.to_string())
    }
    async fn delete(&self, id: i64, revision: i64) -> Result<(), String> {
        let result = sqlx::query("DELETE FROM notes WHERE id=? AND revision=?")
            .bind(id)
            .bind(revision)
            .execute(&self.0)
            .await
            .map_err(|e| e.to_string())?;
        if result.rows_affected() != 1 {
            return Err("Заметка уже изменена. Открой её заново перед удалением.".into());
        }
        Ok(())
    }
}
#[tauri::command]
pub async fn list_notes(store: tauri::State<'_, NotesStore>) -> Result<Vec<Note>, String> {
    store.list().await
}
#[tauri::command]
pub async fn save_note(
    store: tauri::State<'_, NotesStore>,
    id: Option<i64>,
    revision: i64,
    note: NoteInput,
) -> Result<Note, String> {
    store.save(id, revision, note).await
}
#[tauri::command]
pub async fn delete_note(
    store: tauri::State<'_, NotesStore>,
    id: i64,
    revision: i64,
) -> Result<(), String> {
    store.delete(id, revision).await
}

#[cfg(test)]
mod tests {
    use super::*;
    fn input() -> NoteInput {
        NoteInput { category:"shopping".into(), title:"Купить продукты".into(), document:r#"{"type":"doc","content":[{"type":"taskList","content":[{"type":"taskItem","attrs":{"checked":true},"content":[{"type":"paragraph","content":[{"type":"text","text":"Молоко","marks":[{"type":"italic"}]}]}]}]}]}"#.into() }
    }
    #[tokio::test]
    async fn formatting_restart_conflicts_and_delete() {
        let folder = tempfile::tempdir().unwrap();
        let path = folder.path().join("notes.sqlite3");
        let store = NotesStore::open(&path).await.unwrap();
        let saved = store.save(None, 0, input()).await.unwrap();
        assert_eq!(store.summary().await.unwrap(), (0, 0, 1));
        let changed = store
            .save(Some(saved.id), saved.revision, input())
            .await
            .unwrap();
        assert!(store
            .save(Some(saved.id), saved.revision, input())
            .await
            .is_err());
        assert!(store.delete(saved.id, saved.revision).await.is_err());
        store.0.close().await;
        let store = NotesStore::open(&path).await.unwrap();
        let notes = store.list().await.unwrap();
        assert_eq!(notes[0].document, input().document);
        assert_eq!(notes[0].category, "shopping");
        store.delete(changed.id, changed.revision).await.unwrap();
        assert!(store.list().await.unwrap().is_empty());
        assert_eq!(store.summary().await.unwrap(), (0, 0, 0));
        let mut bad = input();
        bad.category = "unknown".into();
        assert!(store.save(None, 0, bad).await.is_err());
        let mut bad = input();
        bad.document = "<script>".into();
        assert!(store.save(None, 0, bad).await.is_err());
        store.0.close().await;
        let _ = std::fs::remove_file(path);
    }
}

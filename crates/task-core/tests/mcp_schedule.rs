use task_core::{NewTask, TaskPatch, TaskStore};

fn task(title: &str, due: Option<&str>) -> NewTask {
    NewTask {
        title: title.into(),
        notes: None,
        due_at: due.map(str::to_owned),
        reminder_at: None,
        priority: None,
    }
}

#[tokio::test]
async fn batch_validation_is_atomic_and_does_not_consume_a_request_key() {
    let dir = tempfile::tempdir().unwrap();
    let store = TaskStore::open_at(dir.path().join("tasks.sqlite3"))
        .await
        .unwrap();
    let invalid = vec![
        task("First", None),
        task("Second", Some("2030-01-02T18:00:00")),
    ];
    assert!(store.create_many_once("plan-1", invalid).await.is_err());
    assert!(store.list(true).await.unwrap().is_empty());
    let saved = store
        .create_many_once("plan-1", vec![task("First", None), task("Second", None)])
        .await
        .unwrap();
    assert_eq!(saved.len(), 2);
    assert!(store.create_many_once("empty", vec![]).await.is_err());
    assert!(store
        .create_many_once("too-many", vec![task("Task", None); 51])
        .await
        .is_err());
    assert!(store
        .create_many_once("bad key", vec![task("Task", None)])
        .await
        .is_err());
    assert_eq!(store.list(true).await.unwrap().len(), 2);
}

#[tokio::test]
async fn retries_survive_restart_preserve_edits_and_never_resurrect_deleted_tasks() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("tasks.sqlite3");
    let store = TaskStore::open_at(&path).await.unwrap();
    let original = task("  Morning  ", Some("2030-01-02T09:00:00+03:00"));
    let saved = store
        .create_many_once("intent-1", vec![original])
        .await
        .unwrap()
        .remove(0);
    let second = TaskStore::open_at(&path).await.unwrap();
    let mut normalized = task("Morning", Some("2030-01-02T06:00:00Z"));
    normalized.priority = Some(0);
    let retry = second
        .create_many_once("intent-1", vec![normalized.clone()])
        .await
        .unwrap();
    assert_eq!(retry[0].id, saved.id);
    assert!(second
        .create_many_once("intent-1", vec![task("Different", None)])
        .await
        .is_err());
    store
        .patch(
            saved.id,
            TaskPatch {
                title: Some("Edited by user".into()),
                notes: None,
                priority: None,
            },
        )
        .await
        .unwrap();
    let retry = second
        .create_many_once("intent-1", vec![normalized.clone()])
        .await
        .unwrap();
    assert_eq!(retry[0].title, "Edited by user");
    second.delete(saved.id).await.unwrap();
    assert!(store
        .create_many_once("intent-1", vec![normalized])
        .await
        .is_err());
    assert!(store.list(true).await.unwrap().is_empty());
}

#[tokio::test]
async fn simultaneous_retries_on_separate_connections_save_one_batch() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("tasks.sqlite3");
    let a = TaskStore::open_at(&path).await.unwrap();
    let b = TaskStore::open_at(&path).await.unwrap();
    let plan = vec![task("First", None), task("Second", None)];
    let (first, second) = tokio::join!(
        a.create_many_once("same-intent", plan.clone()),
        b.create_many_once("same-intent", plan)
    );
    let first = first.unwrap();
    let second = second.unwrap();
    assert_eq!(
        first.iter().map(|t| t.id).collect::<Vec<_>>(),
        second.iter().map(|t| t.id).collect::<Vec<_>>()
    );
    assert_eq!(a.list(true).await.unwrap().len(), 2);
}

#[tokio::test]
async fn calendar_ranges_respect_offsets_boundaries_completion_and_undated_tasks() {
    let dir = tempfile::tempdir().unwrap();
    let store = TaskStore::open_at(dir.path().join("tasks.sqlite3"))
        .await
        .unwrap();
    let start = "2030-01-02T00:00:00+03:00";
    let end = "2030-01-03T00:00:00+03:00";
    let saved = store
        .create_many_once(
            "range",
            vec![
                task("At start", Some(start)),
                task("Inside", Some("2030-01-02T12:00:00+03:00")),
                task("At end", Some(end)),
                task("Undated", None),
            ],
        )
        .await
        .unwrap();
    let tasks = store
        .schedule("2030-01-01T21:00:00Z", end, false)
        .await
        .unwrap();
    assert_eq!(
        tasks.iter().map(|t| t.title.as_str()).collect::<Vec<_>>(),
        ["At start", "Inside"]
    );
    store.set_complete(saved[0].id, true).await.unwrap();
    assert_eq!(store.schedule(start, end, false).await.unwrap().len(), 1);
    assert_eq!(store.schedule(start, end, true).await.unwrap().len(), 2);
    for (start, end) in [
        (end, start),
        (start, start),
        (start, "2031-01-02T00:00:00+03:00"),
        ("2030-01-02T00:00:00", end),
    ] {
        assert!(store.schedule(start, end, false).await.is_err());
    }
}

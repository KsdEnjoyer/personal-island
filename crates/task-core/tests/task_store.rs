use task_core::{NewTask, TaskPatch, TaskStore};

fn new_task(title: &str) -> NewTask {
    NewTask {
        title: title.into(),
        notes: None,
        due_at: None,
        reminder_at: None,
        priority: None,
    }
}

#[tokio::test]
async fn invalid_inputs_do_not_create_tasks() {
    let dir = tempfile::tempdir().unwrap();
    let store = TaskStore::open_at(dir.path().join("test.sqlite3"))
        .await
        .unwrap();
    for title in [" ".to_owned(), "я".repeat(201)] {
        assert!(store.create(new_task(&title)).await.is_err());
    }
    let mut input = new_task("Invalid priority");
    input.priority = Some(3);
    assert!(store.create(input).await.is_err());
    let mut input = new_task("Missing timezone");
    input.due_at = Some("2030-01-02T17:00:00".into());
    assert!(store.create(input).await.is_err());
    assert!(store.list(true).await.unwrap().is_empty());
    assert!(store.create(new_task(&"я".repeat(200))).await.is_ok());
}

#[tokio::test]
async fn separate_connections_share_persisted_tasks() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("test.sqlite3");
    let desktop = TaskStore::open_at(&path).await.unwrap();
    let mcp = TaskStore::open_at(&path).await.unwrap();
    let task = mcp
        .create(new_task("Created through another connection"))
        .await
        .unwrap();
    assert_eq!(desktop.get(task.id).await.unwrap().title, task.title);
    desktop.set_complete(task.id, true).await.unwrap();
    assert!(mcp.list(false).await.unwrap().is_empty());
    assert_eq!(mcp.list(true).await.unwrap()[0].status, "done");
}

#[tokio::test]
async fn invalid_patch_preserves_task_and_missing_ids_fail() {
    let dir = tempfile::tempdir().unwrap();
    let store = TaskStore::open_at(dir.path().join("test.sqlite3"))
        .await
        .unwrap();
    let task = store.create(new_task("Original")).await.unwrap();
    assert!(store
        .patch(
            task.id,
            TaskPatch {
                title: Some("Changed".into()),
                notes: None,
                priority: Some(-1),
            }
        )
        .await
        .is_err());
    assert_eq!(store.get(task.id).await.unwrap().title, "Original");
    assert!(store.get(999).await.is_err());
    assert!(store.set_complete(999, true).await.is_err());
    assert!(store.reschedule(999, None, None).await.is_err());
    assert!(store.delete(999).await.is_err());
}

#[tokio::test]
async fn completed_tasks_are_suppressed_and_reschedule_rearms_reminder() {
    let dir = tempfile::tempdir().unwrap();
    let store = TaskStore::open_at(dir.path().join("test.sqlite3"))
        .await
        .unwrap();
    let mut input = new_task("Reminder lifecycle");
    input.reminder_at = Some("2020-01-01T00:00:00Z".into());
    let task = store.create(input).await.unwrap();
    store.set_complete(task.id, true).await.unwrap();
    assert!(store.due_notifications().await.unwrap().is_empty());
    store.set_complete(task.id, false).await.unwrap();
    assert_eq!(store.due_notifications().await.unwrap().len(), 1);
    store.mark_notified(task.id).await.unwrap();
    assert!(store.due_notifications().await.unwrap().is_empty());
    store
        .reschedule(task.id, None, Some("2020-01-02T00:00:00Z".into()))
        .await
        .unwrap();
    assert_eq!(store.due_notifications().await.unwrap().len(), 1);
    let cleared = store.reschedule(task.id, None, None).await.unwrap();
    assert!(cleared.due_at.is_none() && cleared.reminder_at.is_none());
    assert!(store.due_notifications().await.unwrap().is_empty());
}

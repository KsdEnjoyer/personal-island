use task_core::{NewTask, TaskStore};

#[tokio::test]
async fn displayed_reminder_acknowledges_only_the_open_due_version_once() {
    let dir = tempfile::tempdir().unwrap();
    let store = TaskStore::open_at(dir.path().join("reminders.sqlite3"))
        .await
        .unwrap();
    let task = store
        .create(NewTask {
            title: "Reminder race".into(),
            notes: None,
            due_at: None,
            reminder_at: Some("2020-01-01T00:00:00Z".into()),
            priority: None,
        })
        .await
        .unwrap();
    let old = task.reminder_at.unwrap();
    let changed = store
        .reschedule(task.id, None, Some("2020-01-02T00:00:00Z".into()))
        .await
        .unwrap();
    let current = changed.reminder_at.unwrap();
    assert!(!store.mark_reminder_presented(task.id, &old).await.unwrap());
    assert!(store
        .get(task.id)
        .await
        .unwrap()
        .notification_sent_at
        .is_none());
    assert!(store
        .mark_reminder_presented(task.id, &current)
        .await
        .unwrap());
    assert!(!store
        .mark_reminder_presented(task.id, &current)
        .await
        .unwrap());
    assert!(store.due_notifications().await.unwrap().is_empty());

    store
        .reschedule(task.id, None, Some(old.clone()))
        .await
        .unwrap();
    store.set_complete(task.id, true).await.unwrap();
    assert!(!store.mark_reminder_presented(task.id, &old).await.unwrap());
    store.set_complete(task.id, false).await.unwrap();
    store
        .reschedule(task.id, None, Some("2099-01-01T00:00:00Z".into()))
        .await
        .unwrap();
    assert!(!store
        .mark_reminder_presented(task.id, "2099-01-01T00:00:00Z")
        .await
        .unwrap());
    assert!(store
        .get(task.id)
        .await
        .unwrap()
        .notification_sent_at
        .is_none());
    store.delete(task.id).await.unwrap();
    assert!(!store.mark_reminder_presented(task.id, &old).await.unwrap());
}

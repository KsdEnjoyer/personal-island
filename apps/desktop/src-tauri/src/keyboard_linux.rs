//! Compositor-managed shortcut. Wayland never exposes a pass-through key hook.
use ashpd::desktop::global_shortcuts::{GlobalShortcuts, NewShortcut};
use futures_util::StreamExt;
use std::sync::atomic::AtomicBool;

pub static EDITING: AtomicBool = AtomicBool::new(false);
const SHORTCUT_ID: &str = "dev.personalisland.desktop.toggle";

pub fn start(app: tauri::AppHandle) -> Result<(), String> {
    #[cfg(debug_assertions)]
    if std::env::var("PERSONAL_ISLAND_QA_DISABLE_SHORTCUT").as_deref() == Ok("1") {
        return Ok(());
    }
    if crate::x11_linux::native_session() {
        crate::x11_linux::start_shortcut(app);
        return Ok(());
    }
    tauri::async_runtime::spawn(async move {
        if let Err(error) = listen(app).await {
            eprintln!("Global shortcut portal unavailable: {error}");
        }
    });
    Ok(())
}

async fn listen(app: tauri::AppHandle) -> Result<(), String> {
    let connection = crate::portal_identity_linux::connection().await?;
    let portal = GlobalShortcuts::with_connection(connection)
        .await
        .map_err(|e| e.to_string())?;
    let session = portal
        .create_session(Default::default())
        .await
        .map_err(|e| e.to_string())?;
    let mut activated = portal
        .receive_activated()
        .await
        .map_err(|e| e.to_string())?;
    let previous = portal
        .list_shortcuts(&session, Default::default())
        .await
        .map_err(|e| e.to_string())?;
    let bound = previous
        .response()
        .map_err(|e| e.to_string())?
        .shortcuts()
        .iter()
        .any(|shortcut| shortcut.id() == SHORTCUT_ID);
    if !bound {
        let shortcut = NewShortcut::new(SHORTCUT_ID, "Показать или скрыть Personal Island")
            .preferred_trigger(Some("<Control><Alt>i"));
        portal
            .bind_shortcuts(&session, &[shortcut], None, Default::default())
            .await
            .map_err(|e| e.to_string())?
            .response()
            .map_err(|e| e.to_string())?;
    }
    while let Some(event) = activated.next().await {
        if event.shortcut_id() == SHORTCUT_ID {
            let _ = crate::toggle_island_shortcut(app.clone());
        }
    }
    Ok(())
}

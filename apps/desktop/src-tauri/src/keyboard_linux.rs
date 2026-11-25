//! Compositor-managed shortcut. Wayland never exposes a pass-through key hook.
use ashpd::desktop::global_shortcuts::{GlobalShortcuts, NewShortcut};
use futures_util::StreamExt;
use std::sync::{atomic::AtomicBool, OnceLock};
use tokio::sync::{mpsc, oneshot};

pub static EDITING: AtomicBool = AtomicBool::new(false);
pub static CAPTURING: AtomicBool = AtomicBool::new(false);
const SHORTCUT_ID: &str = "dev.personalisland.desktop.toggle";
type ConfigureReply = oneshot::Sender<Result<(), String>>;
static PORTAL_CONFIGURE: OnceLock<mpsc::Sender<ConfigureReply>> = OnceLock::new();

pub fn configure(shortcut: crate::preferences::Shortcut, _: bool) -> Result<(), String> {
    #[cfg(debug_assertions)]
    if std::env::var("PERSONAL_ISLAND_QA_DISABLE_SHORTCUT").as_deref() == Ok("1") {
        return Ok(());
    }
    if crate::x11_linux::native_session() {
        return crate::x11_linux::configure_shortcut(&shortcut);
    }
    Ok(())
}

#[tauri::command]
pub async fn configure_portal_shortcuts() -> Result<(), String> {
    let message =
        "Открой настройки клавиатуры рабочего стола, чтобы изменить сочетание Personal Island.";
    let (reply, result) = oneshot::channel();
    PORTAL_CONFIGURE
        .get()
        .ok_or(message)?
        .try_send(reply)
        .map_err(|_| message)?;
    tokio::time::timeout(std::time::Duration::from_secs(3), result)
        .await
        .map_err(|_| message)?
        .map_err(|_| message)?
}

pub fn start(app: tauri::AppHandle) -> Result<(), String> {
    #[cfg(debug_assertions)]
    if std::env::var("PERSONAL_ISLAND_QA_DISABLE_SHORTCUT").as_deref() == Ok("1") {
        return Ok(());
    }
    if crate::x11_linux::native_session() {
        if let Err(error) = crate::x11_linux::start_shortcut(app) {
            eprintln!("X11 shortcut unavailable: {error}");
        }
        return Ok(());
    }
    let (configure, requests) = mpsc::channel(1);
    let _ = PORTAL_CONFIGURE.set(configure);
    tauri::async_runtime::spawn(async move {
        if let Err(error) = listen(app, requests).await {
            eprintln!("Global shortcut portal unavailable: {error}");
        }
    });
    Ok(())
}

async fn listen(
    app: tauri::AppHandle,
    mut requests: mpsc::Receiver<ConfigureReply>,
) -> Result<(), String> {
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
    loop {
        tokio::select! {
            event = activated.next() => {
                let Some(event) = event else { break };
                if event.shortcut_id() == SHORTCUT_ID {
                    let _ = crate::toggle_island_shortcut(app.clone());
                }
            }
            Some(reply) = requests.recv() => {
                let result = portal.configure_shortcuts(&session, None, Default::default()).await
                    .map_err(|_| "Открой настройки клавиатуры рабочего стола, чтобы изменить сочетание Personal Island.".into());
                let _ = reply.send(result);
            }
        }
    }
    Ok(())
}

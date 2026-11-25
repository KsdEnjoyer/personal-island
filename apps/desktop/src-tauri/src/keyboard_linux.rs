//! Compositor-managed shortcut. Wayland never exposes a pass-through key hook.
use ashpd::desktop::global_shortcuts::{GlobalShortcuts, NewShortcut, Shortcut};
use futures_util::StreamExt;
use std::sync::{atomic::AtomicBool, Mutex, OnceLock};
use tauri::Emitter;
use tokio::sync::{mpsc, oneshot};

pub static EDITING: AtomicBool = AtomicBool::new(false);
pub static CAPTURING: AtomicBool = AtomicBool::new(false);
static SHORTCUT_LABEL: Mutex<Option<String>> = Mutex::new(None);
const SHORTCUT_ID: &str = "dev.personalisland.desktop.toggle";
const SYSTEM_SHORTCUT_HELP: &str =
    "Назначь запуск Personal Island в настройках клавиатуры рабочего стола.";
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
    let (reply, result) = oneshot::channel();
    PORTAL_CONFIGURE
        .get()
        .ok_or(SYSTEM_SHORTCUT_HELP)?
        .try_send(reply)
        .map_err(|_| SYSTEM_SHORTCUT_HELP)?;
    tokio::time::timeout(std::time::Duration::from_secs(3), result)
        .await
        .map_err(|_| SYSTEM_SHORTCUT_HELP)?
        .map_err(|_| SYSTEM_SHORTCUT_HELP)?
}

pub fn shortcut_label() -> Option<String> {
    SHORTCUT_LABEL.lock().ok()?.clone()
}

pub fn set_shortcut_label(app: &tauri::AppHandle, label: Option<String>) {
    if let Ok(mut current) = SHORTCUT_LABEL.lock() {
        current.clone_from(&label);
    }
    let _ = app.emit("island-shortcut", label);
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
        if let Err(error) = listen(app.clone(), requests).await {
            eprintln!("Global shortcut portal unavailable: {error}");
        }
        set_shortcut_label(&app, None);
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
    let mut closed = session.receive_closed().await.map_err(|e| e.to_string())?;
    let mut activated = portal
        .receive_activated()
        .await
        .map_err(|e| e.to_string())?;
    let mut changed = portal
        .receive_shortcuts_changed()
        .await
        .map_err(|e| e.to_string())?;
    // ListShortcuts can return saved bindings before they are active in this session.
    let shortcut = NewShortcut::new(SHORTCUT_ID, "Показать или скрыть Personal Island")
        .preferred_trigger(Some("CTRL+ALT+i"));
    let bound = portal
        .bind_shortcuts(&session, &[shortcut], None, Default::default())
        .await
        .map_err(|e| e.to_string())?
        .response()
        .map_err(|e| e.to_string())?;
    set_shortcut_label(&app, portal_shortcut_label(bound.shortcuts()));
    loop {
        tokio::select! {
            _ = closed.next() => break,
            event = activated.next() => {
                let Some(event) = event else { break };
                if event.shortcut_id() == SHORTCUT_ID {
                    let _ = crate::toggle_island_shortcut(app.clone());
                }
            }
            event = changed.next() => {
                let Some(event) = event else { break };
                set_shortcut_label(&app, portal_shortcut_label(event.shortcuts()));
            }
            Some(reply) = requests.recv() => {
                let result = portal.configure_shortcuts(&session, None, Default::default()).await
                    .map_err(|_| SYSTEM_SHORTCUT_HELP.into());
                let _ = reply.send(result);
            }
        }
    }
    Ok(())
}

fn portal_shortcut_label(shortcuts: &[Shortcut]) -> Option<String> {
    shortcuts
        .iter()
        .find(|shortcut| shortcut.id() == SHORTCUT_ID)
        .map(Shortcut::trigger_description)
        .filter(|label| !label.is_empty())
        .map(str::to_owned)
}

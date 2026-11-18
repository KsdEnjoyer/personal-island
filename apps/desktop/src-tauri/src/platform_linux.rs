//! A compositor-approved keyboard session for pasting after the island hides.
use ashpd::desktop::{
    remote_desktop::{DeviceType, KeyState, RemoteDesktop, SelectDevicesOptions},
    Session,
};
use std::{
    future::Future,
    sync::atomic::{AtomicBool, AtomicU32, Ordering},
    time::Duration,
};
use tokio::sync::Mutex;

struct KeyboardSession {
    portal: RemoteDesktop,
    session: Session<RemoteDesktop>,
}

#[derive(Default)]
pub struct PasteTarget {
    session: Mutex<Option<KeyboardSession>>,
    pending: AtomicBool,
    previous_window: AtomicU32,
}

impl PasteTarget {
    pub fn remember_foreground(&self) {
        if crate::x11_linux::native_session() {
            self.previous_window.store(
                crate::x11_linux::focused_window().unwrap_or_default(),
                Ordering::SeqCst,
            );
        }
    }

    pub async fn prepare(&self) -> bool {
        if crate::x11_linux::native_session() {
            let ready = self.previous_window.load(Ordering::SeqCst) != 0;
            self.pending.store(ready, Ordering::SeqCst);
            return ready;
        }
        let mut active = self.session.lock().await;
        if active.is_none() {
            match KeyboardSession::connect().await {
                Ok(session) => *active = Some(session),
                Err(error) => {
                    eprintln!("Automatic paste unavailable: {error}");
                    self.pending.store(false, Ordering::SeqCst);
                    return false;
                }
            }
        }
        self.pending.store(true, Ordering::SeqCst);
        true
    }

    pub async fn paste(&self) -> Result<(), String> {
        if !self.pending.swap(false, Ordering::SeqCst) {
            return Err("Сначала выбери запись буфера обмена".into());
        }
        // Hiding the island lets the compositor restore the previous window.
        tokio::time::sleep(Duration::from_millis(180)).await;
        if crate::x11_linux::native_session() {
            let window = self.previous_window.load(Ordering::SeqCst);
            return tokio::task::spawn_blocking(move || crate::x11_linux::paste(window))
                .await
                .map_err(|error| error.to_string())?;
        }
        let mut active = self.session.lock().await;
        let Some(session) = active.as_ref() else {
            return Err("Запись скопирована. Нажми Ctrl+V в нужном окне.".into());
        };
        if let Err(error) = session.paste().await {
            *active = None;
            return Err(format!(
                "Запись скопирована. Вставь её через Ctrl+V: {error}"
            ));
        }
        Ok(())
    }
}

impl KeyboardSession {
    async fn connect() -> Result<Self, String> {
        let connection = crate::portal_identity_linux::connection().await?;
        let portal = RemoteDesktop::with_connection(connection)
            .await
            .map_err(|e| e.to_string())?;
        let session = portal
            .create_session(Default::default())
            .await
            .map_err(|e| e.to_string())?;
        portal
            .select_devices(
                &session,
                SelectDevicesOptions::default().set_devices(Some(DeviceType::Keyboard.into())),
            )
            .await
            .map_err(|e| e.to_string())?
            .response()
            .map_err(|e| e.to_string())?;
        let selected = portal
            .start(&session, None, Default::default())
            .await
            .map_err(|e| e.to_string())?
            .response()
            .map_err(|e| e.to_string())?;
        if !selected.devices().contains(DeviceType::Keyboard) {
            let _ = session.close().await;
            return Err("Система не разрешила управление клавиатурой".into());
        }
        Ok(Self { portal, session })
    }

    async fn paste(&self) -> Result<(), String> {
        send_paste_keys(|code, state| async move {
            self.portal
                .notify_keyboard_keycode(&self.session, code, state, Default::default())
                .await
                .map_err(|e| e.to_string())
        })
        .await
    }
}

async fn send_paste_keys<F, Fut>(mut send: F) -> Result<(), String>
where
    F: FnMut(i32, KeyState) -> Fut,
    Fut: Future<Output = Result<(), String>>,
{
    // Linux evdev KEY_LEFTCTRL=29 and KEY_V=47. Release both even if V fails.
    send(29, KeyState::Pressed).await?;
    let pressed_v = send(47, KeyState::Pressed).await;
    let released_v = send(47, KeyState::Released).await;
    let released_ctrl = send(29, KeyState::Released).await;
    pressed_v.and(released_v).and(released_ctrl)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex as StdMutex};

    #[tokio::test]
    async fn paste_requires_a_prepared_clipboard_entry() {
        assert!(PasteTarget::default().paste().await.is_err());
    }

    #[tokio::test]
    async fn paste_releases_control_after_a_failed_key_event() {
        let calls = Arc::new(StdMutex::new(Vec::new()));
        let result = send_paste_keys(|code, state| {
            let calls = calls.clone();
            async move {
                calls.lock().unwrap().push((code, state));
                if code == 47 && state == KeyState::Pressed {
                    Err("injected failure".into())
                } else {
                    Ok(())
                }
            }
        })
        .await;
        assert!(result.is_err());
        assert_eq!(
            *calls.lock().unwrap(),
            vec![
                (29, KeyState::Pressed),
                (47, KeyState::Pressed),
                (47, KeyState::Released),
                (29, KeyState::Released),
            ]
        );
    }
}

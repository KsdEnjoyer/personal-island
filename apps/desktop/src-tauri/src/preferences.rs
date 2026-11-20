use serde::{Deserialize, Serialize};
use std::{path::PathBuf, sync::Mutex};
use tauri::Manager;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(default)]
pub struct Shortcut {
    pub key: u32,
    pub ctrl: bool,
    pub alt: bool,
    pub shift: bool,
}
impl Default for Shortcut {
    fn default() -> Self {
        Self {
            key: 0xC0,
            ctrl: false,
            alt: false,
            shift: false,
        }
    }
}
impl Shortcut {
    pub fn is_default(&self) -> bool {
        self == &Self::default()
    }
    fn validate(&self) -> Result<(), String> {
        if self.is_default() {
            return Ok(());
        }
        let function = (0x70..=0x87).contains(&self.key) && self.key != 0x7B;
        let character = (0x30..=0x39).contains(&self.key)
            || (0x41..=0x5A).contains(&self.key)
            || [0x20, 0xC0].contains(&self.key);
        if function || (character && (self.ctrl || self.alt)) {
            Ok(())
        } else {
            Err("Выбери Ctrl/Alt с буквой, цифрой или пробелом, либо F1–F11 / F13–F24. F12 зарезервирована Windows.".into())
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(default)]
pub struct WidgetSettings {
    pub shortcut: Shortcut,
    pub review_interval_minutes: u32,
    #[serde(skip_deserializing, skip_serializing_if = "Option::is_none")]
    pub shortcut_error: Option<String>,
}
impl Default for WidgetSettings {
    fn default() -> Self {
        Self {
            shortcut: Shortcut::default(),
            review_interval_minutes: 30,
            shortcut_error: None,
        }
    }
}
impl WidgetSettings {
    fn validate(&self) -> Result<(), String> {
        self.shortcut.validate()?;
        if self.review_interval_minutes != 0 && !(5..=1440).contains(&self.review_interval_minutes)
        {
            return Err("Интервал автопоказа: от 5 до 1440 минут или 0 для отключения.".into());
        }
        Ok(())
    }
}
pub struct Preferences {
    pub value: Mutex<WidgetSettings>,
    path: PathBuf,
    pub changed: tokio::sync::Notify,
}
impl Preferences {
    pub fn load(path: PathBuf) -> Result<Self, String> {
        let value = match std::fs::read(&path) {
            Ok(bytes) => {
                let value: WidgetSettings = serde_json::from_slice(&bytes)
                    .map_err(|e| format!("Не удалось прочитать настройки: {e}"))?;
                value.validate()?;
                value
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => WidgetSettings::default(),
            Err(error) => return Err(error.to_string()),
        };
        Ok(Self {
            value: Mutex::new(value),
            path,
            changed: tokio::sync::Notify::new(),
        })
    }
    fn persist(&self, settings: &WidgetSettings) -> Result<(), String> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let temporary = self.path.with_extension("json.tmp");
        std::fs::write(
            &temporary,
            serde_json::to_vec_pretty(settings).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        std::fs::rename(&temporary, &self.path).map_err(|e| e.to_string())
    }
}
#[tauri::command]
pub fn get_widget_settings(state: tauri::State<'_, Preferences>) -> Result<WidgetSettings, String> {
    Ok(state.value.lock().map_err(|e| e.to_string())?.clone())
}
#[tauri::command]
pub async fn set_widget_settings(
    app: tauri::AppHandle,
    settings: WidgetSettings,
) -> Result<WidgetSettings, String> {
    settings.validate()?;
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<Preferences>();
        let mut current = state.value.lock().map_err(|e| e.to_string())?;
        let mut next = settings;
        next.shortcut_error = None;
        if next.shortcut != current.shortcut {
            crate::keyboard::configure(next.shortcut.clone())?;
        }
        if let Err(error) = state.persist(&next) {
            let _ = crate::keyboard::configure(current.shortcut.clone());
            return Err(format!("Не удалось сохранить настройки: {error}"));
        }
        *current = next.clone();
        state.changed.notify_one();
        Ok(next)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn settings_roundtrip_without_touching_personal_data() {
        let folder = tempfile::tempdir().unwrap();
        let path = folder.path().join("widget-settings.json");
        let store = Preferences::load(path.clone()).unwrap();
        assert_eq!(*store.value.lock().unwrap(), WidgetSettings::default());
        let settings = WidgetSettings {
            shortcut: Shortcut {
                key: 0x49,
                ctrl: true,
                alt: true,
                shift: false,
            },
            review_interval_minutes: 45,
            shortcut_error: None,
        };
        settings.validate().unwrap();
        store.persist(&settings).unwrap();
        store.persist(&settings).unwrap();
        assert_eq!(
            *Preferences::load(path).unwrap().value.lock().unwrap(),
            settings
        );
    }
    #[test]
    fn invalid_intervals_and_typing_keys_are_rejected() {
        for minutes in [1, 4, 1441, u32::MAX] {
            assert!(WidgetSettings {
                review_interval_minutes: minutes,
                ..Default::default()
            }
            .validate()
            .is_err());
        }
        for key in [0x41, 0x7B, 0x10, 0xFF] {
            assert!(Shortcut {
                key,
                ..Default::default()
            }
            .validate()
            .is_err());
        }
        for minutes in [0, 5, 30, 45, 60, 1440] {
            assert!(WidgetSettings {
                review_interval_minutes: minutes,
                ..Default::default()
            }
            .validate()
            .is_ok());
        }
    }
}

//! Host application identity required by newer desktop portals.
use ashpd::{zbus, zvariant};
use std::{collections::HashMap, path::PathBuf};

const APP_ID: &str = "dev.personalisland.desktop";
#[cfg(test)]
const DESKTOP_FILE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/linux/dev.personalisland.desktop.desktop"
);

fn desktop_file_path(data_dir: PathBuf) -> PathBuf {
    data_dir
        .join("applications")
        .join(format!("{APP_ID}.desktop"))
}

fn system_desktop_file_exists() -> bool {
    let dirs =
        std::env::var_os("XDG_DATA_DIRS").unwrap_or_else(|| "/usr/local/share:/usr/share".into());
    dirs.to_string_lossy()
        .split(':')
        .filter(|dir| !dir.is_empty())
        .any(|dir| desktop_file_path(PathBuf::from(dir)).exists())
}

fn ensure_desktop_file() -> Result<(), String> {
    if system_desktop_file_exists() {
        return Ok(());
    }
    let data_dir = std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".local/share")))
        .ok_or("Не найден каталог пользователя для регистрации приложения")?;
    let path = desktop_file_path(data_dir);
    let executable = std::env::var_os("APPIMAGE")
        .map(PathBuf::from)
        .filter(|candidate| candidate.is_file())
        .or_else(|| std::env::current_exe().ok())
        .ok_or("Не найден исполняемый файл приложения")?;
    let contents = include_str!("../linux/dev.personalisland.desktop.desktop").replace(
        "Exec=/usr/bin/personal-island-desktop",
        &format!("Exec={}", quoted_exec_path(&executable)),
    );
    if std::fs::read_to_string(&path).ok().as_deref() != Some(&contents) {
        std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
        std::fs::write(path, contents).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn quoted_exec_path(path: &std::path::Path) -> String {
    let escaped = path
        .to_string_lossy()
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('$', "\\$")
        .replace('`', "\\`")
        .replace('%', "%%");
    format!("\"{escaped}\"")
}

pub async fn connection() -> Result<zbus::Connection, String> {
    ensure_desktop_file()?;
    let connection = zbus::Connection::session()
        .await
        .map_err(|e| e.to_string())?;
    let result = connection
        .call_method(
            Some("org.freedesktop.portal.Desktop"),
            "/org/freedesktop/portal/desktop",
            Some("org.freedesktop.host.portal.Registry"),
            "Register",
            &(APP_ID, HashMap::<String, zvariant::Value<'_>>::new()),
        )
        .await;
    if let Err(error) = result {
        // Older portals do not export Registry and derive the identity themselves.
        if !error.to_string().contains("UnknownMethod") {
            return Err(format!(
                "Не удалось зарегистрировать приложение в портале: {error}"
            ));
        }
    }
    Ok(connection)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn desktop_identity_matches_the_bundle_and_is_hidden_from_app_menu() {
        let contents = std::fs::read_to_string(DESKTOP_FILE).unwrap();
        assert!(contents.contains("NoDisplay=true"));
        assert!(contents.contains("Exec=/usr/bin/personal-island-desktop"));
        assert_eq!(
            quoted_exec_path(std::path::Path::new("/tmp/Personal Island.AppImage")),
            "\"/tmp/Personal Island.AppImage\""
        );
        assert_eq!(
            quoted_exec_path(std::path::Path::new("/tmp/Personal%Island.AppImage")),
            "\"/tmp/Personal%%Island.AppImage\""
        );
        assert_eq!(
            desktop_file_path(PathBuf::from("/usr/share")),
            PathBuf::from("/usr/share/applications/dev.personalisland.desktop.desktop")
        );
    }
}

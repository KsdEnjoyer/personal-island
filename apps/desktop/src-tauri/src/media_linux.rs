//! Linux media control through MPRIS (via playerctl).
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::Serialize;
use std::{
    env,
    io::{Cursor, Read},
    path::{Path, PathBuf},
    process::Command,
    sync::{Mutex, OnceLock},
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager};

#[derive(Serialize, Clone)]
pub struct MediaSource {
    id: String,
    label: String,
}
#[derive(Serialize, Default, Clone)]
pub struct MediaState {
    sessions: Vec<MediaSource>,
    session_id: Option<String>,
    source: String,
    title: String,
    artist: String,
    artwork: Option<String>,
    pub playing: bool,
    position: f64,
    duration: f64,
    can_toggle: bool,
    can_previous: bool,
    can_next: bool,
    can_seek: bool,
}

#[derive(Default)]
pub struct MediaPreference(pub Mutex<Option<String>>);
#[derive(Default)]
pub struct MediaNotifications(Mutex<NotificationState>);
#[derive(Default)]
struct NotificationState {
    previous: String,
    skip_until: Option<Instant>,
}

fn playerctl(args: &[&str]) -> Result<String, String> {
    let output = Command::new("playerctl")
        .args(args)
        .output()
        .map_err(|error| format!("Не удалось запустить playerctl: {error}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

const MPRIS_PLAYER: &str = "org.mpris.MediaPlayer2.Player";

fn mpris_call(id: &str, method: &str, args: &[&str]) -> Result<String, String> {
    let output = Command::new("gdbus")
        .args([
            "call",
            "--session",
            "--timeout",
            "2",
            "--dest",
            &format!("org.mpris.MediaPlayer2.{id}"),
            "--object-path",
            "/org/mpris/MediaPlayer2",
            "--method",
            method,
        ])
        .args(args)
        .output()
        .map_err(|error| error.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_owned());
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn can_seek(id: &str) -> bool {
    mpris_call(
        id,
        "org.freedesktop.DBus.Properties.Get",
        &[MPRIS_PLAYER, "CanSeek"],
    )
    .as_deref()
        == Ok("(<true>,)")
}

#[tauri::command]
pub async fn seek_media(session_id: String, position: f64, title: String) -> Result<(), String> {
    if !position.is_finite() || position < 0.0 {
        return Err("Некорректная позиция трека.".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        if !can_seek(&session_id) {
            return Err("Перемотка недоступна в этом плеере.".into());
        }
        let metadata = playerctl(&[
            "-p",
            &session_id,
            "metadata",
            "--format",
            "{{mpris:trackid}}\u{1f}{{mpris:length}}\u{1f}{{xesam:title}}",
        ])?;
        let mut fields = metadata.splitn(3, '\u{1f}');
        let track = fields
            .next()
            .filter(|id| id.starts_with('/') && *id != "/org/mpris/MediaPlayer2/TrackList/NoTrack")
            .ok_or("Плеер не предоставил идентификатор трека.")?;
        let length = fields
            .next()
            .and_then(|value| value.parse::<i64>().ok())
            .filter(|length| *length > 0)
            .ok_or("Плеер не предоставил длительность трека.")?;
        if fields.next().unwrap_or_default() != title {
            return Err("Трек уже сменился. Попробуй перемотать ещё раз.".into());
        }
        let micros = ((position * 1_000_000.0).round() as i64).min(length);
        mpris_call(
            &session_id,
            "org.mpris.MediaPlayer2.Player.SetPosition",
            &[track, &micros.to_string()],
        )?;
        Ok(())
    })
    .await
    .map_err(|error| error.to_string())?
}

fn source_label(id: &str) -> String {
    if is_yandex_music_player(id) {
        "Яндекс Музыка".into()
    } else {
        id.split('.').next().unwrap_or(id).to_string()
    }
}

fn is_yandex_music_player(id: &str) -> bool {
    let id = id.to_lowercase();
    id.contains("yandex") && id.contains("music")
}

fn yandex_desktop_entry_in(dirs: impl IntoIterator<Item = PathBuf>) -> Option<PathBuf> {
    dirs.into_iter().find_map(|dir| {
        std::fs::read_dir(dir.join("applications"))
            .ok()?
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .find(|path| {
                path.extension().is_some_and(|ext| ext == "desktop")
                    && path
                        .file_name()
                        .and_then(|name| name.to_str())
                        .is_some_and(is_yandex_music_player)
            })
    })
}

fn yandex_desktop_entry() -> Option<PathBuf> {
    let mut dirs = Vec::new();
    if let Some(data) = env::var_os("XDG_DATA_HOME") {
        dirs.push(PathBuf::from(data));
    } else if let Some(home) = env::var_os("HOME") {
        dirs.push(PathBuf::from(home).join(".local/share"));
    }
    dirs.extend(
        env::var_os("XDG_DATA_DIRS")
            .unwrap_or_else(|| "/usr/local/share:/usr/share".into())
            .to_string_lossy()
            .split(':')
            .filter(|dir| !dir.is_empty())
            .map(PathBuf::from),
    );
    yandex_desktop_entry_in(dirs)
}

fn launch_desktop_entry(path: &Path) -> Result<(), String> {
    let output = Command::new("gio")
        .arg("launch")
        .arg(path)
        .output()
        .map_err(|error| format!("Не удалось открыть Яндекс Музыку: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "Не удалось открыть Яндекс Музыку: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(())
}

struct CachedArtwork {
    uri: String,
    image: Option<String>,
    checked_at: Instant,
}

fn artwork(uri: &str) -> Option<String> {
    static CACHE: OnceLock<Mutex<Option<CachedArtwork>>> = OnceLock::new();
    let mut cache = CACHE.get_or_init(|| Mutex::new(None)).lock().ok()?;
    if let Some(cached) = cache.as_ref() {
        if cached.uri == uri
            && cached.checked_at.elapsed()
                < if cached.image.is_some() {
                    Duration::from_secs(600)
                } else {
                    Duration::from_secs(30)
                }
        {
            return cached.image.clone();
        }
    }
    let image = load_artwork(uri);
    *cache = Some(CachedArtwork {
        uri: uri.to_owned(),
        image: image.clone(),
        checked_at: Instant::now(),
    });
    image
}

fn load_artwork(uri: &str) -> Option<String> {
    const LIMIT: u64 = 2 * 1024 * 1024;
    let bytes = if let Some(path) = crate::clipboard_formats::decode_uri(uri) {
        if std::fs::metadata(&path).ok()?.len() > LIMIT {
            return None;
        }
        std::fs::read(path).ok()?
    } else if uri.starts_with("https://") || uri.starts_with("http://") {
        let response = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(4))
            .build()
            .ok()?
            .get(uri)
            .send()
            .ok()?
            .error_for_status()
            .ok()?;
        if response.content_length().is_some_and(|size| size > LIMIT) {
            return None;
        }
        let mut bytes = Vec::new();
        response.take(LIMIT + 1).read_to_end(&mut bytes).ok()?;
        if bytes.len() as u64 > LIMIT {
            return None;
        }
        bytes
    } else {
        return None;
    };
    let image = image::load_from_memory(&bytes).ok()?.thumbnail(280, 280);
    let mut png = Cursor::new(Vec::new());
    image.write_to(&mut png, image::ImageFormat::Png).ok()?;
    Some(format!(
        "data:image/png;base64,{}",
        STANDARD.encode(png.into_inner())
    ))
}

fn snapshot(preferred: Option<String>) -> Result<MediaState, String> {
    let ids = playerctl(&["--list-all"])?;
    let mut ids: Vec<String> = ids
        .lines()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .collect();
    let sources = ids
        .iter()
        .map(|id| MediaSource {
            id: id.clone(),
            label: source_label(id),
        })
        .collect();
    ids.sort_by_key(|id| {
        (
            preferred.as_deref() != Some(id.as_str()),
            playerctl(&["-p", id, "status"]).as_deref() != Ok("Playing"),
            !is_yandex_music_player(id),
        )
    });
    let Some(id) = ids.first() else {
        return Ok(MediaState {
            sessions: sources,
            ..Default::default()
        });
    };
    let status = playerctl(&["-p", id, "status"]).unwrap_or_default();
    let metadata = playerctl(&[
        "-p",
        id,
        "metadata",
        "--format",
        "{{xesam:title}}\u{1f}{{xesam:artist}}\u{1f}{{mpris:artUrl}}\u{1f}{{mpris:length}}",
    ])
    .unwrap_or_default();
    let mut fields = metadata.split('\u{1f}');
    let title = fields.next().unwrap_or_default().to_string();
    let artist = fields.next().unwrap_or_default().to_string();
    let art = fields.next().and_then(artwork);
    let duration = fields
        .next()
        .and_then(|s| s.trim().parse::<f64>().ok())
        .unwrap_or(0.0)
        / 1_000_000.0;
    let position = playerctl(&["-p", id, "position"])
        .ok()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(0.0);
    Ok(MediaState {
        sessions: sources,
        session_id: Some(id.clone()),
        source: source_label(id),
        title,
        artist,
        artwork: art,
        playing: status == "Playing",
        position,
        duration,
        can_toggle: status != "Stopped",
        can_previous: true,
        can_next: true,
        can_seek: duration > 0.0 && can_seek(id),
    })
}

#[tauri::command]
pub async fn get_media_state(
    app: tauri::AppHandle,
    preferred: Option<String>,
) -> Result<MediaState, String> {
    *app.state::<MediaPreference>()
        .0
        .lock()
        .map_err(|e| e.to_string())? = preferred.clone();
    tauri::async_runtime::spawn_blocking(move || snapshot(preferred))
        .await
        .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn media_command(
    app: tauri::AppHandle,
    session_id: String,
    action: String,
) -> Result<(), String> {
    let command = match action.as_str() {
        "toggle" => "play-pause",
        "previous" => "previous",
        "next" => "next",
        _ => return Err("Неизвестная команда плеера".into()),
    };
    let id = session_id.clone();
    tauri::async_runtime::spawn_blocking(move || playerctl(&["-p", &id, command]).map(|_| ()))
        .await
        .map_err(|e| e.to_string())??;
    if matches!(action.as_str(), "previous" | "next") {
        app.state::<MediaNotifications>()
            .0
            .lock()
            .map_err(|e| e.to_string())?
            .skip_until = Some(Instant::now() + Duration::from_secs(6));
    }
    Ok(())
}

#[tauri::command]
pub fn open_yandex_music() -> Result<(), String> {
    if let Some(path) = yandex_desktop_entry() {
        return launch_desktop_entry(&path);
    }
    Command::new("xdg-open")
        .arg("https://music.yandex.ru/")
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn start_yandex_music(app: tauri::AppHandle) -> Result<MediaState, String> {
    let state = tauri::async_runtime::spawn_blocking(start_yandex_playback)
        .await
        .map_err(|e| e.to_string())??;
    *app.state::<MediaPreference>()
        .0
        .lock()
        .map_err(|e| e.to_string())? = state.session_id.clone();
    let _ = app.emit("media-changed", &state);
    Ok(state)
}

fn start_yandex_playback() -> Result<MediaState, String> {
    let deadline = Instant::now() + Duration::from_secs(20);
    let mut launched = false;
    let mut next_play = Instant::now();
    while Instant::now() < deadline {
        let player = playerctl(&["--list-all"])
            .unwrap_or_default()
            .lines()
            .find(|id| is_yandex_music_player(id))
            .map(str::to_owned);
        if let Some(id) = player {
            let state = snapshot(Some(id.clone()))?;
            if state.session_id.as_deref() == Some(id.as_str()) && state.playing {
                return Ok(state);
            }
            if Instant::now() >= next_play {
                // Play is idempotent. A retry must not pause a newly started track.
                let _ = playerctl(&["-p", &id, "play"]);
                next_play = Instant::now() + Duration::from_secs(1);
            }
        } else if !launched {
            let path = yandex_desktop_entry().ok_or(
                "Установи настольную Яндекс Музыку с music.yandex.ru/download/ и войди в аккаунт. Кнопка «Яндекс Музыка» открывает сайт.",
            )?;
            launch_desktop_entry(&path)?;
            launched = true;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    Err("Яндекс Музыка открыта, но MPRIS не сообщил о воспроизведении. Проверь вход в аккаунт и очередь треков, затем нажми Play ещё раз.".into())
}

pub async fn watch(app: tauri::AppHandle) {
    let mut ticker = tokio::time::interval(Duration::from_secs(2));
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        ticker.tick().await;
        if app.get_webview_window("main").is_none() {
            break;
        }
        let preferred = app
            .state::<MediaPreference>()
            .0
            .lock()
            .ok()
            .and_then(|value| value.clone());
        if let Ok(Ok(state)) =
            tauri::async_runtime::spawn_blocking(move || snapshot(preferred)).await
        {
            let changed = {
                let notifications_state = app.state::<MediaNotifications>();
                let mut notifications = notifications_state
                    .0
                    .lock()
                    .unwrap_or_else(|e| e.into_inner());
                let key = format!("{:?}|{}|{}", state.session_id, state.title, state.artist);
                let changed =
                    state.playing && !state.title.is_empty() && key != notifications.previous;
                notifications.previous = key;
                if notifications
                    .skip_until
                    .is_some_and(|until| until > Instant::now())
                {
                    false
                } else {
                    changed
                }
            };
            let _ = app.emit("media-changed", &state);
            if changed {
                let _ = crate::reveal_compact(&app, "track");
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn desktop_entry_finds_yandex_music_without_matching_browser() {
        let root = tempfile::tempdir().unwrap();
        let applications = root.path().join("applications");
        std::fs::create_dir(&applications).unwrap();
        std::fs::write(applications.join("yandex-browser.desktop"), "").unwrap();
        let expected = applications.join("YandexMusic.desktop");
        std::fs::write(&expected, "").unwrap();
        assert_eq!(
            yandex_desktop_entry_in([root.path().to_path_buf()]),
            Some(expected)
        );
        assert!(!is_yandex_music_player("yandex-browser.instance123"));
    }
}

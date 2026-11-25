//! Linux media control through MPRIS (via playerctl).
use ashpd::{
    zbus,
    zvariant::{ObjectPath, OwnedValue},
};
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::Serialize;
use std::{
    collections::HashMap,
    env,
    io::{Cursor, Read},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{Mutex, OnceLock},
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum MusicApp {
    YandexMusic,
    #[serde(rename = "spotify-app")]
    Spotify,
}

impl MusicApp {
    const ALL: [Self; 2] = [Self::YandexMusic, Self::Spotify];

    fn id(self) -> &'static str {
        match self {
            Self::YandexMusic => "yandex-music",
            Self::Spotify => "spotify-app",
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::YandexMusic => "Яндекс Музыка",
            Self::Spotify => "Spotify",
        }
    }

    fn matches_desktop_entry(self, name: &str) -> bool {
        match self {
            Self::YandexMusic => is_yandex_music_player(name),
            Self::Spotify => matches!(
                name.to_ascii_lowercase().as_str(),
                "spotify.desktop" | "com.spotify.client.desktop" | "spotify_spotify.desktop"
            ),
        }
    }
}

#[derive(Serialize, Clone)]
pub struct MediaSource {
    id: String,
    label: String,
    app: Option<MusicApp>,
}
#[derive(Serialize, Default, Clone)]
pub struct MediaState {
    sessions: Vec<MediaSource>,
    preference: Option<String>,
    available_apps: Vec<MusicApp>,
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
    let output = match Command::new("playerctl").args(args).output() {
        Ok(output) => output,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound && args == ["--list-all"] => {
            return Ok(String::new());
        }
        Err(error) => return Err(format!("Не удалось запустить playerctl: {error}")),
    };
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

const MPRIS_PLAYER: &str = "org.mpris.MediaPlayer2.Player";
const MPRIS_NO_TRACK: &str = "/org/mpris/MediaPlayer2/TrackList/NoTrack";

async fn mpris_player<'a>(
    connection: &zbus::Connection,
    id: &'a str,
) -> Result<zbus::Proxy<'a>, zbus::Error> {
    zbus::Proxy::new(
        connection,
        format!("org.mpris.MediaPlayer2.{id}"),
        "/org/mpris/MediaPlayer2",
        MPRIS_PLAYER,
    )
    .await
}

#[derive(Default)]
struct TrackMetadata {
    title: String,
    artist: String,
    artwork: String,
    length_micros: i64,
    can_seek: bool,
}

fn metadata_text<'a>(values: &'a HashMap<String, OwnedValue>, key: &str) -> &'a str {
    values
        .get(key)
        .and_then(|value| <&str>::try_from(value).ok())
        .unwrap_or_default()
}

fn track_path(values: &HashMap<String, OwnedValue>) -> Option<ObjectPath<'_>> {
    let value = values.get("mpris:trackid")?;
    // Some players return the path as a string rather than an object path.
    let path = <&ObjectPath>::try_from(value)
        .cloned()
        .ok()
        .or_else(|| ObjectPath::try_from(<&str>::try_from(value).ok()?).ok())?;
    (path.as_str() != MPRIS_NO_TRACK && path.as_str() != "/").then_some(path)
}

fn track_length(values: &HashMap<String, OwnedValue>) -> i64 {
    values
        .get("mpris:length")
        .and_then(|value| i64::try_from(value).ok())
        .unwrap_or_default()
}

async fn mpris_metadata(id: &str) -> Result<TrackMetadata, zbus::Error> {
    let connection = zbus::Connection::session().await?;
    let player = mpris_player(&connection, id).await?;
    let values: HashMap<String, OwnedValue> = player.get_property("Metadata").await?;
    let length_micros = track_length(&values);
    let artist = values
        .get("xesam:artist")
        .and_then(|value| value.try_clone().ok())
        .and_then(|value| Vec::<String>::try_from(value).ok())
        .map(|artists| artists.join(", "))
        .unwrap_or_else(|| metadata_text(&values, "xesam:artist").to_owned());
    Ok(TrackMetadata {
        title: metadata_text(&values, "xesam:title").to_owned(),
        artist,
        artwork: metadata_text(&values, "mpris:artUrl").to_owned(),
        length_micros,
        can_seek: length_micros > 0
            && track_path(&values).is_some()
            && player.get_property("CanSeek").await.unwrap_or(false),
    })
}

fn track_metadata(id: &str) -> TrackMetadata {
    let result = tauri::async_runtime::block_on(async {
        tokio::time::timeout(Duration::from_secs(2), mpris_metadata(id)).await
    });
    if let Ok(Ok(metadata)) = result {
        return metadata;
    }
    let metadata = playerctl(&[
        "-p",
        id,
        "metadata",
        "--format",
        "{{xesam:title}}\u{1f}{{xesam:artist}}\u{1f}{{mpris:artUrl}}\u{1f}{{mpris:length}}",
    ])
    .unwrap_or_default();
    let mut fields = metadata.split('\u{1f}');
    TrackMetadata {
        title: fields.next().unwrap_or_default().to_owned(),
        artist: fields.next().unwrap_or_default().to_owned(),
        artwork: fields.next().unwrap_or_default().to_owned(),
        length_micros: fields
            .next()
            .and_then(|value| value.parse().ok())
            .unwrap_or_default(),
        ..Default::default()
    }
}

#[tauri::command]
pub async fn seek_media(session_id: String, position: f64, title: String) -> Result<(), String> {
    if !position.is_finite() || position < 0.0 {
        return Err("Некорректная позиция трека.".into());
    }
    tokio::time::timeout(Duration::from_secs(3), async {
        let connection = zbus::Connection::session()
            .await
            .map_err(|error| error.to_string())?;
        let player = mpris_player(&connection, &session_id)
            .await
            .map_err(|error| error.to_string())?;
        if !player.get_property("CanSeek").await.unwrap_or(false) {
            return Err("Перемотка недоступна в этом плеере.".into());
        }
        let values: HashMap<String, OwnedValue> = player
            .get_property("Metadata")
            .await
            .map_err(|error| error.to_string())?;
        let track = track_path(&values).ok_or("Плеер не предоставил идентификатор трека.")?;
        let length = track_length(&values);
        if length <= 0 {
            return Err("Плеер не предоставил длительность трека.".into());
        }
        if metadata_text(&values, "xesam:title") != title {
            return Err("Трек уже сменился. Попробуй перемотать ещё раз.".into());
        }
        let micros = ((position * 1_000_000.0).round() as i64).min(length);
        player
            .call("SetPosition", &(track, micros))
            .await
            .map_err(|error| error.to_string())
    })
    .await
    .map_err(|_| "Плеер не ответил на перемотку.".to_string())?
}

fn is_yandex_music_player(id: &str) -> bool {
    let id = id.to_lowercase();
    id.contains("yandex") && id.contains("music")
}

fn yandex_music_session(id: &str) -> bool {
    let application = id.split('.').next().unwrap_or(id);
    if is_yandex_music_player(application) {
        return true;
    }
    if !matches!(application, "chromium" | "chrome" | "electron") {
        return false;
    }
    // Electron publishes a Chromium bus name even for the installed desktop app.
    crate::volume::mpris_owner_pid(id)
        .and_then(|pid| std::fs::read_link(format!("/proc/{pid}/exe")).ok())
        .and_then(|path| path.file_name()?.to_str().map(is_yandex_music_player))
        .unwrap_or(false)
}

fn media_sources() -> Result<Vec<MediaSource>, String> {
    let ids = match playerctl(&["--list-all"]) {
        Ok(ids) => ids,
        Err(error) if error.is_empty() || error == "No players found" => return Ok(Vec::new()),
        Err(error) => return Err(error),
    };
    Ok(ids
        .lines()
        .filter(|id| !id.is_empty())
        .map(|id| {
            let name = id.split('.').next().unwrap_or(id);
            let app = match name {
                "spotify" => Some(MusicApp::Spotify),
                _ if yandex_music_session(id) => Some(MusicApp::YandexMusic),
                _ => None,
            };
            MediaSource {
                id: id.into(),
                label: app
                    .map(|app| app.label().to_owned())
                    .unwrap_or_else(|| name.to_owned()),
                app,
            }
        })
        .collect())
}

fn select_source<'a>(
    sources: &'a [MediaSource],
    preferred: Option<&str>,
    is_playing: impl Fn(&str) -> bool,
) -> Option<&'a MediaSource> {
    let bound = MusicApp::ALL
        .into_iter()
        .find(|app| preferred == Some(app.id()));
    sources
        .iter()
        .filter(|source| bound.is_none() || source.app == bound)
        .min_by_key(|source| {
            (
                bound.is_none() && preferred.is_some_and(|id| id != source.id),
                !is_playing(&source.id),
                source.app.is_none(),
            )
        })
}

fn desktop_entry_in(app: MusicApp, dirs: impl IntoIterator<Item = PathBuf>) -> Option<PathBuf> {
    dirs.into_iter().find_map(|dir| {
        std::fs::read_dir(dir.join("applications"))
            .ok()?
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .find(|path| {
                path.is_file()
                    && path.extension().is_some_and(|ext| ext == "desktop")
                    && path
                        .file_name()
                        .and_then(|name| name.to_str())
                        .is_some_and(|name| app.matches_desktop_entry(name))
            })
    })
}

fn desktop_entry(app: MusicApp) -> Option<PathBuf> {
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
    if app == MusicApp::Spotify {
        if let Some(home) = env::var_os("HOME") {
            dirs.push(PathBuf::from(home).join(".local/share/flatpak/exports/share"));
        }
        dirs.extend([
            PathBuf::from("/var/lib/flatpak/exports/share"),
            PathBuf::from("/var/lib/snapd/desktop"),
        ]);
    }
    desktop_entry_in(app, dirs)
}

fn launch_desktop_entry(app: MusicApp, path: &Path) -> Result<(), String> {
    // The launched player can inherit gio's streams and keep captured pipes open.
    let status = Command::new("gio")
        .arg("launch")
        .arg(path)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|error| format!("Не удалось открыть {}: {error}", app.label()))?;
    if !status.success() {
        return Err(format!("Не удалось открыть {}: {status}", app.label()));
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
    let sources = media_sources()?;
    let available_apps = MusicApp::ALL
        .into_iter()
        .filter(|app| {
            sources.iter().any(|source| source.app == Some(*app)) || desktop_entry(*app).is_some()
        })
        .collect();
    let selected = select_source(&sources, preferred.as_deref(), |id| {
        playerctl(&["-p", id, "status"]).as_deref() == Ok("Playing")
    });
    let Some(selected) = selected else {
        return Ok(MediaState {
            sessions: sources,
            preference: preferred,
            available_apps,
            ..Default::default()
        });
    };
    let id = &selected.id;
    let status = playerctl(&["-p", id, "status"]).unwrap_or_default();
    let metadata = track_metadata(id);
    let duration = metadata.length_micros.max(0) as f64 / 1_000_000.0;
    let art = artwork(&metadata.artwork);
    let position = playerctl(&["-p", id, "position"])
        .ok()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(0.0);
    Ok(MediaState {
        preference: preferred,
        available_apps,
        session_id: Some(id.clone()),
        source: selected.label.clone(),
        sessions: sources,
        title: metadata.title,
        artist: metadata.artist,
        artwork: art,
        playing: status == "Playing",
        position,
        duration,
        can_toggle: status != "Stopped",
        can_previous: true,
        can_next: true,
        can_seek: metadata.can_seek,
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
pub async fn open_yandex_music() -> Result<(), String> {
    open_app(MusicApp::YandexMusic).await
}

#[tauri::command]
pub async fn start_yandex_music() -> Result<MediaState, String> {
    start_app(MusicApp::YandexMusic).await
}

#[tauri::command]
pub async fn open_spotify() -> Result<(), String> {
    open_app(MusicApp::Spotify).await
}

async fn open_app(app: MusicApp) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        if let Some(path) = desktop_entry(app) {
            return launch_desktop_entry(app, &path);
        }
        match app {
            MusicApp::YandexMusic => Command::new("xdg-open")
                .arg("https://music.yandex.ru/")
                .spawn()
                .map(|_| ())
                .map_err(|error| error.to_string()),
            MusicApp::Spotify => raise_spotify(),
        }
    })
    .await
    .map_err(|error| error.to_string())?
}

fn raise_spotify() -> Result<(), String> {
    let player = media_sources()?
        .into_iter()
        .find(|source| source.app == Some(MusicApp::Spotify))
        .ok_or("Установи и открой настольный Spotify.")?;
    let status = Command::new("gdbus")
        .args([
            "call",
            "--session",
            "--dest",
            &format!("org.mpris.MediaPlayer2.{}", player.id),
            "--object-path",
            "/org/mpris/MediaPlayer2",
            "--method",
            "org.mpris.MediaPlayer2.Raise",
            "--timeout",
            "5",
        ])
        .output()
        .map_err(|error| error.to_string())?;
    if !status.status.success() {
        return Err("Открой окно Spotify из меню приложений.".into());
    }
    Ok(())
}

#[tauri::command]
pub async fn start_spotify() -> Result<MediaState, String> {
    start_app(MusicApp::Spotify).await
}

async fn start_app(app: MusicApp) -> Result<MediaState, String> {
    tauri::async_runtime::spawn_blocking(move || start_playback(app))
        .await
        .map_err(|e| e.to_string())?
}

fn start_playback(app: MusicApp) -> Result<MediaState, String> {
    let deadline = Instant::now() + Duration::from_secs(20);
    let mut launched = false;
    let mut next_play = Instant::now();
    while Instant::now() < deadline {
        let player = media_sources()
            .unwrap_or_default()
            .into_iter()
            .find(|source| source.app == Some(app))
            .map(|source| source.id);
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
            let path = desktop_entry(app).ok_or_else(|| {
                format!(
                    "Установи настольное приложение «{}» и войди в аккаунт.",
                    app.label()
                )
            })?;
            launch_desktop_entry(app, &path)?;
            launched = true;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    Err(format!(
        "В «{}» не началось воспроизведение. Проверь вход в аккаунт и включи трек в приложении.",
        app.label()
    ))
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
    fn yandex_binding_follows_new_sessions_without_using_the_browser() {
        let browser = MediaSource {
            id: "chromium.instance11".into(),
            label: "chromium".into(),
            app: None,
        };
        let yandex = MediaSource {
            id: "chromium.instance22".into(),
            label: "Яндекс Музыка".into(),
            app: Some(MusicApp::YandexMusic),
        };
        let spotify = MediaSource {
            id: "spotify.instance33".into(),
            label: "Spotify".into(),
            app: Some(MusicApp::Spotify),
        };
        let sources = [browser, yandex, spotify];
        let is_playing = |id: &str| id == "chromium.instance11";
        let pinned = Some(MusicApp::YandexMusic.id());
        assert!(select_source(&sources[..1], pinned, is_playing).is_none());
        assert_eq!(
            select_source(&sources, pinned, is_playing).unwrap().id,
            sources[1].id
        );
        assert_eq!(
            select_source(&sources, None, is_playing).unwrap().id,
            sources[0].id
        );
        let spotify_binding = Some(MusicApp::Spotify.id());
        assert!(select_source(&sources[..2], spotify_binding, is_playing).is_none());
        assert_eq!(
            select_source(&sources, spotify_binding, is_playing)
                .unwrap()
                .id,
            sources[2].id
        );
    }

    #[test]
    fn desktop_entry_finds_yandex_music_without_matching_browser() {
        let root = tempfile::tempdir().unwrap();
        let applications = root.path().join("applications");
        std::fs::create_dir(&applications).unwrap();
        std::fs::write(applications.join("yandex-browser.desktop"), "").unwrap();
        let expected = applications.join("YandexMusic.desktop");
        std::fs::write(&expected, "").unwrap();
        assert_eq!(
            desktop_entry_in(MusicApp::YandexMusic, [root.path().to_path_buf()]),
            Some(expected)
        );
        assert!(!is_yandex_music_player("yandex-browser.instance123"));
        let spotify = applications.join("com.spotify.Client.desktop");
        std::fs::write(&spotify, "").unwrap();
        assert_eq!(
            desktop_entry_in(MusicApp::Spotify, [root.path().to_path_buf()]),
            Some(spotify)
        );
    }
}

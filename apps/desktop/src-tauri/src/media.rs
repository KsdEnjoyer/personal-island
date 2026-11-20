use base64::{engine::general_purpose::STANDARD, Engine};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::io::Cursor;
use std::sync::{Arc, Mutex, OnceLock};
use std::{
    collections::{HashMap, HashSet},
    time::{Duration, Instant},
};
use windows::{
    Media::Control::{
        GlobalSystemMediaTransportControlsSession as Session,
        GlobalSystemMediaTransportControlsSessionManager as Manager,
        GlobalSystemMediaTransportControlsSessionMediaProperties as Properties,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
    },
    Storage::Streams::DataReader,
    Win32::System::WinRT::{RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED},
};

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

struct Runtime;
struct SeekAnchor {
    source: String,
    title: String,
    stamp: i64,
    position: f64,
    at: Instant,
    playing: bool,
}
impl SeekAnchor {
    fn project(
        &mut self,
        source: &str,
        title: &str,
        stamp: i64,
        playing: bool,
        duration: f64,
        now: Instant,
    ) -> Option<f64> {
        if self.source != source || self.title != title || stamp > self.stamp {
            return None;
        }
        if self.playing {
            self.position += now.saturating_duration_since(self.at).as_secs_f64();
        }
        self.at = now;
        self.playing = playing;
        self.position = self.position.clamp(0.0, duration.max(0.0));
        Some(self.position)
    }
}
static SEEK_ANCHOR: OnceLock<Mutex<Option<SeekAnchor>>> = OnceLock::new();
fn seek_anchor() -> &'static Mutex<Option<SeekAnchor>> {
    SEEK_ANCHOR.get_or_init(Mutex::default)
}
#[derive(Default)]
pub struct MediaPreference(std::sync::Mutex<Option<String>>);
#[derive(Default)]
pub struct MediaNotifications(Arc<Mutex<TrackNotifications>>);
struct LocalSkip {
    token: u64,
    from_title: String,
    result_title: Option<String>,
    expires: Instant,
}
#[derive(Default)]
struct TrackNotifications {
    revision: u64,
    previous: String,
    titles: HashMap<String, String>,
    local: HashMap<String, LocalSkip>,
}
impl TrackNotifications {
    fn command(&mut self, source: &str, skip: bool, now: Instant) -> u64 {
        self.revision += 1;
        if skip {
            self.local.insert(
                source.to_owned(),
                LocalSkip {
                    token: self.revision,
                    from_title: self.titles.get(source).cloned().unwrap_or_default(),
                    result_title: None,
                    expires: now + Duration::from_secs(6),
                },
            );
        }
        self.revision
    }
    fn failed(&mut self, source: &str, token: u64) {
        if self
            .local
            .get(source)
            .is_some_and(|skip| skip.token == token)
        {
            self.local.remove(source);
        }
    }
    fn baseline(&mut self, source: &str, token: u64, title: String) {
        if let Some(skip) = self
            .local
            .get_mut(source)
            .filter(|skip| skip.token == token)
        {
            skip.from_title = title;
            skip.result_title = None;
        }
    }
    fn observe(&mut self, state: &MediaState, now: Instant) -> bool {
        self.local.retain(|_, skip| skip.expires > now);
        if !state.playing || state.title.trim().is_empty() {
            return false;
        }
        let key = format!("{:?}|{}|{}", state.session_id, state.title, state.artist);
        let changed = key != self.previous;
        self.previous = key;
        let Some(source) = state.session_id.as_deref() else {
            return false;
        };
        self.titles.insert(source.to_owned(), state.title.clone());
        if let Some(skip) = self.local.get_mut(source) {
            if let Some(result) = &skip.result_title {
                // Late artwork/artist metadata for this same result must not reopen it.
                if result == &state.title {
                    return false;
                }
                self.local.remove(source);
            } else {
                if skip.from_title != state.title {
                    skip.result_title = Some(state.title.clone());
                }
                return false;
            }
        }
        changed
    }
}
impl Runtime {
    fn new() -> Result<Self, String> {
        unsafe { RoInitialize(RO_INIT_MULTITHREADED) }.map_err(|e| e.to_string())?;
        Ok(Self)
    }
}
impl Drop for Runtime {
    fn drop(&mut self) {
        unsafe { RoUninitialize() }
    }
}
fn is_yandex_music(id: &str) -> bool {
    let lower = id.to_lowercase();
    lower.contains("yandexmusic")
        || lower.contains("yandex.music")
        || lower == "ru.yandex.desktop.music"
}
fn label(id: &str) -> String {
    let lower = id.to_lowercase();
    if is_yandex_music(id) {
        "Яндекс Музыка".into()
    } else if lower.contains("yandex") || lower == "browser.exe" {
        "Яндекс Браузер".into()
    } else {
        id.rsplit(['\\', '/'])
            .next()
            .unwrap_or(id)
            .trim_end_matches(".exe")
            .to_string()
    }
}
fn sessions(manager: &Manager) -> windows::core::Result<Vec<(String, Session)>> {
    let list = manager.GetSessions()?;
    let mut result = Vec::new();
    for index in 0..list.Size()? {
        if let Ok(session) = list.GetAt(index) {
            if session
                .GetPlaybackInfo()
                .and_then(|info| info.PlaybackStatus())
                .ok()
                == Some(Status::Closed)
            {
                continue;
            }
            if let Ok(id) = session.SourceAppUserModelId() {
                result.push((id.to_string(), session));
            }
        }
    }
    // Windows can retain an old session after a process restarts. Metadata and
    // commands must resolve the same live instance, not different equal IDs.
    let current = manager.GetCurrentSession().ok();
    result.sort_by_cached_key(|(_, session)| {
        let playing = session
            .GetPlaybackInfo()
            .and_then(|info| info.PlaybackStatus())
            .ok()
            == Some(Status::Playing);
        let updated = session
            .GetTimelineProperties()
            .and_then(|t| t.LastUpdatedTime())
            .map(|t| t.UniversalTime)
            .unwrap_or(0);
        std::cmp::Reverse((current.as_ref() == Some(session), playing, updated))
    });
    let mut seen = HashSet::new();
    result.retain(|(id, _)| seen.insert(id.clone()));
    Ok(result)
}
fn artwork(props: &Properties) -> Option<String> {
    let stream = props.Thumbnail().ok()?.OpenReadAsync().ok()?.join().ok()?;
    let size = stream.Size().ok()?;
    if size == 0 || size > 2 * 1024 * 1024 {
        return None;
    }
    let reader = DataReader::CreateDataReader(&stream.GetInputStreamAt(0).ok()?).ok()?;
    let count = reader.LoadAsync(size as u32).ok()?.join().ok()?;
    let mut bytes = vec![0; count as usize];
    reader.ReadBytes(&mut bytes).ok()?;
    // Thumbnail metadata may arrive after the title, so key by actual image bytes.
    // One bounded entry shared by the watcher and explicit frontend refreshes.
    static CACHE: OnceLock<Mutex<ArtworkCache>> = OnceLock::new();
    CACHE
        .get_or_init(Mutex::default)
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .read(&bytes)
}
#[derive(Default)]
struct ArtworkCache {
    digest: Option<[u8; 32]>,
    url: Option<String>,
}
impl ArtworkCache {
    fn read(&mut self, bytes: &[u8]) -> Option<String> {
        self.read_with(bytes, encode_artwork)
    }
    fn read_with(
        &mut self,
        bytes: &[u8],
        encode: impl FnOnce(&[u8]) -> Option<String>,
    ) -> Option<String> {
        let digest: [u8; 32] = Sha256::digest(bytes).into();
        if self.digest != Some(digest) {
            self.url = encode(bytes);
            self.digest = Some(digest);
        }
        self.url.clone()
    }
}
fn encode_artwork(bytes: &[u8]) -> Option<String> {
    let image = image::load_from_memory(bytes).ok()?.thumbnail(280, 280);
    let mut png = Cursor::new(Vec::new());
    image.write_to(&mut png, image::ImageFormat::Png).ok()?;
    Some(format!(
        "data:image/png;base64,{}",
        STANDARD.encode(png.into_inner())
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn a_paused_seek_ignores_stale_metadata_until_a_fresh_timeline_or_track() {
        let now = Instant::now();
        let mut anchor = SeekAnchor {
            source: "fixture".into(),
            title: "One".into(),
            stamp: 100,
            position: 60.0,
            at: now,
            playing: false,
        };
        assert_eq!(
            anchor.project(
                "fixture",
                "One",
                100,
                false,
                180.0,
                now + Duration::from_secs(30)
            ),
            Some(60.0)
        );
        assert_eq!(
            anchor.project(
                "fixture",
                "One",
                100,
                true,
                180.0,
                now + Duration::from_secs(31)
            ),
            Some(60.0)
        );
        assert_eq!(
            anchor.project(
                "fixture",
                "One",
                100,
                true,
                180.0,
                now + Duration::from_secs(33)
            ),
            Some(62.0)
        );
        assert_eq!(
            anchor.project("fixture", "One", 101, false, 180.0, now),
            None
        );
        assert_eq!(
            anchor.project("fixture", "Two", 100, false, 180.0, now),
            None
        );
        assert_eq!(anchor.project("other", "One", 100, false, 180.0, now), None);
    }
    #[test]
    fn seek_uses_relative_seconds_clamps_to_track_and_rejects_bad_input() {
        assert_eq!(
            seek_ticks(12.5, 50_000_000, 650_000_000).unwrap(),
            175_000_000
        );
        assert_eq!(
            seek_ticks(500.0, 50_000_000, 650_000_000).unwrap(),
            650_000_000
        );
        for value in [-1.0, f64::NAN, f64::INFINITY] {
            assert!(seek_ticks(value, 0, 600_000_000).is_err());
        }
        assert!(seek_ticks(0.0, 100, 100).is_err());
    }
    #[test]
    fn yandex_launch_targets_music_instead_of_browser_media() {
        for id in ["ru.yandex.desktop.music", "YandexMusic.exe", "Yandex.Music"] {
            assert!(is_yandex_music(id));
            assert_eq!(label(id), "Яндекс Музыка");
        }
        for id in ["browser.exe", "YandexBrowser", "chrome.exe", "qa-media.exe"] {
            assert!(!is_yandex_music(id));
        }
    }
    fn track(source: &str, title: &str) -> MediaState {
        MediaState {
            session_id: Some(source.into()),
            title: title.into(),
            artist: "Artist".into(),
            playing: true,
            ..Default::default()
        }
    }
    #[test]
    fn local_skips_update_metadata_without_notifications_but_external_changes_still_notify() {
        let now = Instant::now();
        let mut notifications = TrackNotifications::default();
        assert!(notifications.observe(&track("player", "One"), now));
        let token = notifications.command("player", true, now);
        notifications.baseline("player", token, "One".into());
        assert!(!notifications.observe(&track("player", "One"), now));
        assert!(!notifications.observe(&track("player", "Two"), now));
        let mut late_metadata = track("player", "Two");
        late_metadata.artist = "Updated artist".into();
        assert!(!notifications.observe(&late_metadata, now));
        // This external change is immediate: no blanket time-based notification mute.
        assert!(notifications.observe(&track("player", "Three"), now));
        assert!(!notifications.observe(&track("player", "Three"), now));
    }
    #[test]
    fn rapid_commands_failures_expiration_and_other_sources_do_not_hide_external_changes() {
        let now = Instant::now();
        let mut notifications = TrackNotifications::default();
        notifications.observe(&track("player", "One"), now);
        let old = notifications.command("player", true, now);
        let current = notifications.command("player", true, now);
        notifications.baseline("player", current, "Two".into());
        notifications.failed("player", old);
        assert!(!notifications.observe(&track("player", "Two"), now));
        assert!(!notifications.observe(&track("player", "Three"), now));
        assert!(notifications.observe(&track("other", "One"), now));
        let failed = notifications.command("player", true, now);
        notifications.failed("player", failed);
        assert!(notifications.observe(&track("player", "Four"), now));
        notifications.command("player", true, now);
        assert!(notifications.observe(&track("player", "Five"), now + Duration::from_secs(7)));
    }
    #[test]
    fn repeated_artwork_skips_encoding_but_new_bytes_refresh_even_for_the_same_track() {
        let mut cache = ArtworkCache::default();
        let mut encodes = 0;
        for _ in 0..20 {
            assert_eq!(
                cache.read_with(b"cover one", |_| {
                    encodes += 1;
                    Some("first image".into())
                }),
                Some("first image".into())
            );
        }
        assert_eq!(encodes, 1);
        assert_eq!(
            cache.read_with(b"cover two", |_| Some("updated image".into())),
            Some("updated image".into())
        );
        assert_eq!(cache.read_with(b"no image", |_| None), None);
    }
}
fn snapshot(preferred: Option<String>) -> Result<MediaState, String> {
    let _runtime = Runtime::new()?;
    let manager = Manager::RequestAsync()
        .and_then(|operation| operation.join())
        .map_err(|e| e.to_string())?;
    let mut list = sessions(&manager).map_err(|e| e.to_string())?;
    let sources = list
        .iter()
        .map(|(id, _)| MediaSource {
            id: id.clone(),
            label: label(id),
        })
        .collect();
    let current = manager
        .GetCurrentSession()
        .ok()
        .and_then(|session| session.SourceAppUserModelId().ok())
        .map(|id| id.to_string());
    list.sort_by_key(|(id, session)| {
        let yandex = id.to_lowercase().contains("yandex") || id == "browser.exe";
        let playing = session
            .GetPlaybackInfo()
            .and_then(|info| info.PlaybackStatus())
            .ok()
            == Some(Status::Playing);
        (
            preferred.as_ref() != Some(id),
            !is_yandex_music(id),
            !playing,
            !yandex,
            current.as_ref() != Some(id),
        )
    });
    let Some((id, session)) = list.first() else {
        *seek_anchor().lock().unwrap_or_else(|e| e.into_inner()) = None;
        return Ok(MediaState {
            sessions: sources,
            ..Default::default()
        });
    };
    let props = session
        .TryGetMediaPropertiesAsync()
        .and_then(|operation| operation.join())
        .map_err(|e| e.to_string())?;
    let info = session.GetPlaybackInfo().map_err(|e| e.to_string())?;
    let controls = info.Controls().map_err(|e| e.to_string())?;
    let playing = info.PlaybackStatus().ok() == Some(Status::Playing);
    let (mut position, duration, timeline_stamp) = session
        .GetTimelineProperties()
        .ok()
        .map(|timeline| {
            let start = timeline.StartTime().map(|time| time.Duration).unwrap_or(0);
            let end = timeline
                .EndTime()
                .map(|time| time.Duration)
                .unwrap_or(start);
            let mut position = timeline
                .Position()
                .map(|time| time.Duration)
                .unwrap_or(start);
            if playing {
                if let Ok(updated) = timeline.LastUpdatedTime() {
                    let now = chrono::Utc::now()
                        .timestamp_millis()
                        .saturating_mul(10_000)
                        .saturating_add(116_444_736_000_000_000);
                    let elapsed = now.saturating_sub(updated.UniversalTime);
                    // Ignore missing/implausible provider timestamps.
                    if (0..=864_000_000_000).contains(&elapsed) {
                        position = position.saturating_add(elapsed);
                    }
                }
            }
            (
                ((position.clamp(start, end.max(start)) - start).max(0) as f64) / 10_000_000.0,
                ((end - start).max(0) as f64) / 10_000_000.0,
                timeline
                    .LastUpdatedTime()
                    .map(|time| time.UniversalTime)
                    .unwrap_or(0),
            )
        })
        .unwrap_or((0.0, 0.0, 0));
    let title = props
        .Title()
        .map(|value| value.to_string())
        .unwrap_or_default();
    {
        let mut anchor = seek_anchor().lock().unwrap_or_else(|e| e.into_inner());
        if let Some(previous) = anchor.as_mut() {
            if let Some(projected) = previous.project(
                id,
                &title,
                timeline_stamp,
                playing,
                duration,
                Instant::now(),
            ) {
                position = projected;
            } else {
                *anchor = None;
            }
        }
    }
    Ok(MediaState {
        sessions: sources,
        session_id: Some(id.clone()),
        source: label(id),
        title,
        artist: props
            .Artist()
            .map(|value| value.to_string())
            .unwrap_or_default(),
        artwork: artwork(&props),
        playing,
        position,
        duration,
        can_toggle: controls.IsPlayPauseToggleEnabled().unwrap_or(false)
            || if playing {
                controls.IsPauseEnabled().unwrap_or(false)
            } else {
                controls.IsPlayEnabled().unwrap_or(false)
            },
        can_previous: controls.IsPreviousEnabled().unwrap_or(false),
        can_next: controls.IsNextEnabled().unwrap_or(false),
        can_seek: duration > 0.0 && controls.IsPlaybackPositionEnabled().unwrap_or(false),
    })
}

fn seek_ticks(seconds: f64, start: i64, end: i64) -> Result<i64, String> {
    if !seconds.is_finite() || seconds < 0.0 || end <= start {
        return Err("Позиция трека недоступна или некорректна.".into());
    }
    let relative = (seconds * 10_000_000.0)
        .round()
        .min((end.saturating_sub(start)) as f64) as i64;
    Ok(start.saturating_add(relative).min(end))
}

#[tauri::command]
pub async fn seek_media(session_id: String, position: f64, title: String) -> Result<(), String> {
    if !position.is_finite() || position < 0.0 {
        return Err("Некорректная позиция трека.".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let _runtime = Runtime::new()?;
        let manager = Manager::RequestAsync()
            .and_then(|operation| operation.join())
            .map_err(|e| e.to_string())?;
        let (_, session) = sessions(&manager)
            .map_err(|e| e.to_string())?
            .into_iter()
            .find(|(id, _)| id == &session_id)
            .ok_or("Плеер уже закрыт.")?;
        let current_title = session
            .TryGetMediaPropertiesAsync()
            .and_then(|op| op.join())
            .and_then(|props| props.Title())
            .map_err(|e| e.to_string())?;
        if current_title.to_string() != title {
            return Err("Трек уже сменился. Попробуй перемотать ещё раз.".into());
        }
        let controls = session
            .GetPlaybackInfo()
            .and_then(|info| info.Controls())
            .map_err(|e| e.to_string())?;
        if !controls.IsPlaybackPositionEnabled().unwrap_or(false) {
            return Err("Этот плеер не поддерживает перемотку через Windows.".into());
        }
        let timeline = session.GetTimelineProperties().map_err(|e| e.to_string())?;
        let ticks = seek_ticks(
            position,
            timeline.StartTime().map_err(|e| e.to_string())?.Duration,
            timeline.EndTime().map_err(|e| e.to_string())?.Duration,
        )?;
        if !session
            .TryChangePlaybackPositionAsync(ticks)
            .and_then(|op| op.join())
            .map_err(|e| e.to_string())?
        {
            return Err("Плеер отклонил перемотку. Попробуй ещё раз.".into());
        }
        // Some providers keep their old public timeline while paused even
        // though playback has moved. Keep the requested position until a
        // newer provider timestamp, a different track, or a closed session.
        let start = timeline.StartTime().map_err(|e| e.to_string())?.Duration;
        *seek_anchor().lock().unwrap_or_else(|e| e.into_inner()) = Some(SeekAnchor {
            source: session_id,
            title,
            stamp: timeline
                .LastUpdatedTime()
                .map(|t| t.UniversalTime)
                .unwrap_or(0),
            position: (ticks - start) as f64 / 10_000_000.0,
            at: Instant::now(),
            playing: session
                .GetPlaybackInfo()
                .and_then(|info| info.PlaybackStatus())
                .ok()
                == Some(Status::Playing),
        });
        Ok(())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn get_media_state(
    app: tauri::AppHandle,
    preferred: Option<String>,
) -> Result<MediaState, String> {
    use tauri::Manager;
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
    use tauri::Manager as _;
    let notifications = app.state::<MediaNotifications>().0.clone();
    let token = notifications
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .command(
            &session_id,
            matches!(action.as_str(), "previous" | "next"),
            Instant::now(),
        );
    let source = session_id.clone();
    let command_notifications = notifications.clone();
    let result = tauri::async_runtime::spawn_blocking(move || {
        let _runtime = Runtime::new()?;
        let manager = Manager::RequestAsync()
            .and_then(|operation| operation.join())
            .map_err(|e| e.to_string())?;
        let (_, session) = sessions(&manager)
            .map_err(|e| e.to_string())?
            .into_iter()
            .find(|(id, _)| id == &session_id)
            .ok_or("Плеер уже закрыт. Запусти музыку снова.")?;
        if matches!(action.as_str(), "previous" | "next") {
            if let Ok(props) = session
                .TryGetMediaPropertiesAsync()
                .and_then(|operation| operation.join())
            {
                if let Ok(title) = props.Title() {
                    command_notifications
                        .lock()
                        .unwrap_or_else(|e| e.into_inner())
                        .baseline(&session_id, token, title.to_string());
                }
            }
        }
        let operation = match action.as_str() {
            "toggle" => {
                let playing = session
                    .GetPlaybackInfo()
                    .and_then(|info| info.PlaybackStatus())
                    .ok()
                    == Some(Status::Playing);
                if playing {
                    session.TryPauseAsync()
                } else {
                    session.TryPlayAsync()
                }
            }
            "previous" => session.TrySkipPreviousAsync(),
            "next" => session.TrySkipNextAsync(),
            _ => return Err("Неизвестная команда плеера".into()),
        }
        .map_err(|e| e.to_string())?;
        if operation.join().map_err(|e| e.to_string())? {
            Ok(())
        } else {
            Err("Плеер не поддерживает эту команду.".into())
        }
    })
    .await
    .map_err(|e| e.to_string())
    .and_then(|result| result);
    if result.is_err() {
        notifications
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .failed(&source, token);
    }
    result
}

#[tauri::command]
pub fn open_yandex_music() -> Result<(), String> {
    // A fixed URL only, never a shell command supplied by the WebView.
    std::process::Command::new("rundll32.exe")
        .args(["url.dll,FileProtocolHandler", "https://music.yandex.ru/"])
        .creation_flags(0x08000000)
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

fn installed_yandex_music() -> Option<std::path::PathBuf> {
    let mut folders = Vec::new();
    if let Some(root) = std::env::var_os("LOCALAPPDATA") {
        folders.push(
            std::path::PathBuf::from(root)
                .join("Programs")
                .join("YandexMusic"),
        );
    }
    for variable in ["ProgramFiles", "ProgramFiles(x86)"] {
        if let Some(root) = std::env::var_os(variable) {
            folders.push(std::path::PathBuf::from(root).join("YandexMusic"));
        }
    }
    folders.into_iter().find_map(|folder| {
        ["Яндекс Музыка.exe", "YandexMusic.exe"]
            .into_iter()
            .map(|name| folder.join(name))
            .find(|path| path.is_file())
    })
}

fn start_yandex_playback() -> Result<MediaState, String> {
    let _runtime = Runtime::new()?;
    let manager = Manager::RequestAsync()
        .and_then(|operation| operation.join())
        .map_err(|e| e.to_string())?;
    let deadline = Instant::now() + Duration::from_secs(25);
    let mut next_play = Instant::now();
    let mut next_initial_play = Instant::now() + Duration::from_secs(3);
    let mut initial_play_sent = false;
    let executable = installed_yandex_music();
    let mut launched = false;
    while Instant::now() < deadline {
        // Windows can briefly retain a disconnected session after a player exits.
        let ready = sessions(&manager).ok().and_then(|list| {
            list.into_iter().find_map(|(id, session)| {
                if !is_yandex_music(&id) {
                    return None;
                }
                let status = session.GetPlaybackInfo().ok()?.PlaybackStatus().ok()?;
                (status != Status::Closed).then_some((id, session, status))
            })
        });
        if let Some((id, session, status)) = ready {
            if status == Status::Playing {
                if let Ok(state) = snapshot(Some(id.clone())) {
                    if state.playing && state.session_id.as_deref() == Some(id.as_str()) {
                        return Ok(state);
                    }
                }
            } else if Instant::now() >= next_play {
                // Explicit Play is idempotent: retries can never pause playback.
                let _ = session
                    .TryPlayAsync()
                    .and_then(|operation| operation.join());
                next_play = Instant::now() + Duration::from_secs(1);
            }
        } else if !launched {
            let executable = executable.as_ref().ok_or(
                "Для запуска одним нажатием установи настольную Яндекс Музыку и войди в аккаунт. Кнопка «Яндекс Музыка» открывает сайт.",
            )?;
            // Fixed installed executable, no arbitrary command or debug endpoint.
            std::process::Command::new(executable)
                .env_remove("ELECTRON_RUN_AS_NODE")
                .args([
                    "--force-renderer-accessibility=complete",
                    "--enable-features=UiaProvider",
                ])
                .creation_flags(0x08000000)
                .spawn()
                .map_err(|e| format!("Не удалось запустить Яндекс Музыку: {e}"))?;
            launched = true;
        }
        if !initial_play_sent && Instant::now() >= next_initial_play {
            if let Some(executable) = executable.as_ref() {
                initial_play_sent = crate::music_start::initial_play(executable);
            }
            next_initial_play = Instant::now() + Duration::from_secs(1);
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    Err("Яндекс Музыка открыта, но трек не запустился. Проверь вход в аккаунт и очередь воспроизведения, затем нажми Play ещё раз.".into())
}

#[tauri::command]
pub async fn start_yandex_music(app: tauri::AppHandle) -> Result<MediaState, String> {
    use tauri::{Emitter, Manager as _};
    let playing = tauri::async_runtime::spawn_blocking(start_yandex_playback)
        .await
        .map_err(|e| e.to_string())??;
    *app.state::<MediaPreference>()
        .0
        .lock()
        .map_err(|e| e.to_string())? = playing.session_id.clone();
    let _ = app.emit("media-changed", &playing);
    Ok(playing)
}
use std::os::windows::process::CommandExt;

/// Poll on native time even while the WebView is hidden/throttled.
pub async fn watch(app: tauri::AppHandle) {
    use tauri::{Emitter, Manager};
    let mut ticker = tokio::time::interval(std::time::Duration::from_secs(2));
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
            .and_then(|p| p.clone());
        let notifications = app.state::<MediaNotifications>().0.clone();
        let revision = notifications
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .revision;
        if let Ok(Ok(state)) =
            tauri::async_runtime::spawn_blocking(move || snapshot(preferred)).await
        {
            let changed = {
                let mut notifications = notifications.lock().unwrap_or_else(|e| e.into_inner());
                // A command can finish while a preceding snapshot is still being read.
                if revision != notifications.revision {
                    continue;
                }
                notifications.observe(&state, Instant::now())
            };
            let _ = app.emit("media-changed", &state);
            if changed {
                let _ = crate::reveal_compact(&app, "track");
            }
        }
    }
}

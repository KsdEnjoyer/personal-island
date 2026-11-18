use base64::{engine::general_purpose::STANDARD, Engine};
use image::{DynamicImage, ImageFormat, RgbaImage};
use serde::Serialize;
use sha2::{Digest, Sha256};
use sqlx::{
    sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions},
    FromRow, SqlitePool,
};
use std::{
    borrow::Cow,
    io::Cursor,
    path::Path,
    sync::{
        atomic::{AtomicBool, AtomicU32, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tauri::{Emitter, Manager};
#[cfg(windows)]
use windows::{
    core::w,
    Win32::{
        Foundation::HGLOBAL,
        System::{
            DataExchange::{
                CloseClipboard, GetClipboardData, GetClipboardSequenceNumber,
                IsClipboardFormatAvailable, OpenClipboard, RegisterClipboardFormatW,
            },
            Memory::{GlobalLock, GlobalSize, GlobalUnlock},
        },
    },
};

const MAX_PAYLOAD: usize = 8 * 1024 * 1024;
const HISTORY_BYTES: i64 = 64 * 1024 * 1024;
const PIN_BYTES: i64 = 32 * 1024 * 1024;

#[derive(Clone, Serialize, FromRow, Debug)]
pub struct Entry {
    pub id: i64,
    pub kind: String,
    pub text: Option<String>,
    pub thumbnail: Option<String>,
    pub width: Option<i64>,
    pub height: Option<i64>,
    pub pinned: bool,
    pub captured_at: i64,
    #[serde(skip)]
    files_json: Option<String>,
    #[sqlx(skip)]
    pub files: Vec<ClipboardFile>,
}
#[derive(Clone, Serialize, Debug)]
pub struct ClipboardFile {
    pub path: String,
    pub name: String,
}
#[derive(Serialize)]
pub struct History {
    pub enabled: bool,
    pub entries: Vec<Entry>,
}
pub struct ClipboardState {
    pool: SqlitePool,
    enabled: AtomicBool,
    sequence: AtomicU32,
    gate: Mutex<()>,
}

impl ClipboardState {
    pub async fn summary(&self) -> Result<(bool, i64, i64), String> {
        let (count, pinned): (i64, i64) =
            sqlx::query_as("SELECT MIN(COUNT(*),9),COALESCE(SUM(pinned),0) FROM clipboard_history")
                .fetch_one(&self.pool)
                .await
                .map_err(|e| e.to_string())?;
        Ok((self.enabled.load(Ordering::SeqCst), count, pinned))
    }
    pub async fn open(path: &Path) -> Result<Self, String> {
        let opts = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .busy_timeout(Duration::from_secs(3));
        let pool = SqlitePoolOptions::new()
            .max_connections(3)
            .connect_with(opts)
            .await
            .map_err(|e| e.to_string())?;
        sqlx::query("CREATE TABLE IF NOT EXISTS clipboard_history (id INTEGER PRIMARY KEY, digest BLOB NOT NULL UNIQUE, kind TEXT NOT NULL, text TEXT, payload BLOB, thumbnail TEXT, width INTEGER, height INTEGER, pinned INTEGER NOT NULL DEFAULT 0, captured_at INTEGER NOT NULL)").execute(&pool).await.map_err(|e| e.to_string())?;
        sqlx::query("CREATE TABLE IF NOT EXISTS clipboard_settings (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL)").execute(&pool).await.map_err(|e| e.to_string())?;
        let enabled: Option<bool> =
            sqlx::query_scalar("SELECT enabled FROM clipboard_settings WHERE id=1")
                .fetch_optional(&pool)
                .await
                .map_err(|e| e.to_string())?;
        Ok(Self {
            pool,
            enabled: AtomicBool::new(enabled.unwrap_or(false)),
            sequence: AtomicU32::new(clipboard_sequence()),
            gate: Mutex::new(()),
        })
    }

    async fn save(
        &self,
        kind: &str,
        text: Option<&str>,
        payload: Option<&[u8]>,
        thumbnail: Option<&str>,
        dimensions: Option<(u32, u32)>,
    ) -> Result<(), String> {
        let mut digest = Sha256::new();
        digest.update(kind);
        digest.update(text.map(str::as_bytes).or(payload).unwrap_or_default());
        let hash = digest.finalize().to_vec();
        let mut tx = self.pool.begin().await.map_err(|e| e.to_string())?;
        sqlx::query("INSERT INTO clipboard_history(digest,kind,text,payload,thumbnail,width,height,captured_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(digest) DO UPDATE SET captured_at=excluded.captured_at,thumbnail=excluded.thumbnail,width=excluded.width,height=excluded.height,text=excluded.text,payload=excluded.payload")
            .bind(hash).bind(kind).bind(text).bind(payload).bind(thumbnail).bind(dimensions.map(|d| d.0 as i64)).bind(dimensions.map(|d| d.1 as i64)).bind(chrono::Utc::now().timestamp_millis()).execute(&mut *tx).await.map_err(|e| e.to_string())?;
        sqlx::query("DELETE FROM clipboard_history WHERE pinned=0 AND id NOT IN (SELECT id FROM clipboard_history WHERE pinned=0 ORDER BY captured_at DESC,id DESC LIMIT 100)").execute(&mut *tx).await.map_err(|e| e.to_string())?;
        loop {
            let bytes:i64=sqlx::query_scalar("SELECT COALESCE(SUM(COALESCE(length(payload),0)+COALESCE(length(CAST(text AS BLOB)),0)),0) FROM clipboard_history").fetch_one(&mut *tx).await.map_err(|e| e.to_string())?;
            if bytes <= HISTORY_BYTES {
                break;
            }
            let result=sqlx::query("DELETE FROM clipboard_history WHERE id=(SELECT id FROM clipboard_history WHERE pinned=0 ORDER BY captured_at,id LIMIT 1)").execute(&mut *tx).await.map_err(|e| e.to_string())?;
            if result.rows_affected() == 0 {
                break;
            }
        }
        tx.commit().await.map_err(|e| e.to_string())
    }
    async fn save_text(&self, text: &str) -> Result<(), String> {
        if text.trim().is_empty() || text.len() > 256 * 1024 {
            return Ok(());
        }
        self.save("text", Some(text), None, None, None).await
    }
    async fn save_image(&self, image: arboard::ImageData<'_>) -> Result<(), String> {
        if image.width == 0
            || image.height == 0
            || image.width.saturating_mul(image.height) > 16_000_000
        {
            return Ok(());
        }
        let rgba = RgbaImage::from_raw(
            image.width as u32,
            image.height as u32,
            image.bytes.into_owned(),
        )
        .ok_or("Неверный формат картинки")?;
        let image = DynamicImage::ImageRgba8(rgba);
        let encode = |image: &DynamicImage| -> Result<Vec<u8>, String> {
            let mut cursor = Cursor::new(Vec::new());
            image
                .write_to(&mut cursor, ImageFormat::Png)
                .map_err(|e| e.to_string())?;
            Ok(cursor.into_inner())
        };
        let png = encode(&image)?;
        if png.len() > MAX_PAYLOAD {
            return Ok(());
        }
        let thumb = format!(
            "data:image/png;base64,{}",
            STANDARD.encode(encode(&image.thumbnail(200, 120))?)
        );
        self.save(
            "image",
            None,
            Some(&png),
            Some(&thumb),
            Some((image.width(), image.height())),
        )
        .await
    }
    async fn save_files(&self, paths: Vec<String>) -> Result<(), String> {
        if paths.is_empty()
            || paths.len() > crate::clipboard_formats::MAX_FILES
            || paths
                .iter()
                .any(|path| !Path::new(path).is_absolute() || path.contains('\0'))
        {
            return Ok(());
        }
        let payload = serde_json::to_vec(&paths).map_err(|e| e.to_string())?;
        if payload.len() > 256 * 1024 {
            return Ok(());
        }
        let mut thumbnail = None;
        // Preview local image files only. No recursive scan or network share reads.
        for path in paths.iter().take(4).filter(|path| !path.starts_with(r"\\")) {
            if std::fs::metadata(path)
                .ok()
                .is_none_or(|meta| !meta.is_file() || meta.len() > 8 * 1024 * 1024)
            {
                continue;
            }
            let dimensions = image::ImageReader::open(path)
                .ok()
                .and_then(|r| r.with_guessed_format().ok())
                .and_then(|r| r.into_dimensions().ok());
            if dimensions
                .is_none_or(|(w, h)| w == 0 || h == 0 || (w as u64) * (h as u64) > 16_000_000)
            {
                continue;
            }
            if let Ok(image) = image::open(path) {
                let mut png = Cursor::new(Vec::new());
                if image
                    .thumbnail(200, 120)
                    .write_to(&mut png, ImageFormat::Png)
                    .is_ok()
                {
                    thumbnail = Some(format!(
                        "data:image/png;base64,{}",
                        STANDARD.encode(png.into_inner())
                    ));
                    break;
                }
            }
        }
        self.save(
            "files",
            Some(&paths.join("\n")),
            Some(&payload),
            thumbnail.as_deref(),
            None,
        )
        .await
    }
    async fn save_png(&self, bytes: Vec<u8>) -> Result<(), String> {
        let dimensions = image::ImageReader::with_format(Cursor::new(&bytes), ImageFormat::Png)
            .into_dimensions()
            .map_err(|e| e.to_string())?;
        if dimensions.0 == 0
            || dimensions.1 == 0
            || dimensions.0 as u64 * dimensions.1 as u64 > 16_000_000
        {
            return Ok(());
        }
        let image = image::load_from_memory_with_format(&bytes, ImageFormat::Png)
            .map_err(|e| e.to_string())?
            .to_rgba8();
        self.save_image(arboard::ImageData {
            width: image.width() as usize,
            height: image.height() as usize,
            bytes: Cow::Owned(image.into_raw()),
        })
        .await
    }
    async fn list(&self, search: &str) -> Result<History, String> {
        self.view(search, false).await
    }
    async fn view(&self, search: &str, pinned_only: bool) -> Result<History, String> {
        // Select the recent window before searching. An old match or pin must
        // not displace a newer copy in the default nine-item view.
        let mut entries=sqlx::query_as::<_,Entry>("SELECT id,kind,text,thumbnail,width,height,pinned,captured_at,CASE WHEN kind='files' THEN CAST(payload AS TEXT) ELSE NULL END AS files_json FROM clipboard_history WHERE (? OR id IN (SELECT id FROM clipboard_history ORDER BY captured_at DESC,id DESC LIMIT 9)) AND (?=0 OR pinned=1) ORDER BY captured_at DESC,id DESC")
            .bind(pinned_only).bind(pinned_only).fetch_all(&self.pool).await.map_err(|e|e.to_string())?;
        let query = search.trim().to_lowercase();
        entries.retain(|entry| {
            query.is_empty()
                || entry
                    .text
                    .as_deref()
                    .unwrap_or("изображение картинка image")
                    .to_lowercase()
                    .contains(&query)
        });
        for entry in &mut entries {
            if let Some(json) = entry.files_json.take() {
                let paths: Vec<String> = serde_json::from_str(&json).map_err(|e| e.to_string())?;
                entry.files = paths
                    .into_iter()
                    .map(|path| ClipboardFile {
                        name: Path::new(&path)
                            .file_name()
                            .map(|s| s.to_string_lossy().into_owned())
                            .unwrap_or_else(|| path.clone()),
                        path,
                    })
                    .collect();
            }
            if let Some(text) = &mut entry.text {
                *text = text.chars().take(2000).collect();
            }
        }
        Ok(History {
            enabled: self.enabled.load(Ordering::SeqCst),
            entries,
        })
    }
}

// Respect common password-manager opt-out markers before reading payloads.
#[cfg(windows)]
fn excluded() -> bool {
    unsafe {
        for name in [
            w!("ExcludeClipboardContentFromMonitorProcessing"),
            w!("Clipboard Viewer Ignore"),
        ] {
            if IsClipboardFormatAvailable(RegisterClipboardFormatW(name)).is_ok() {
                return true;
            }
        }
        let format = RegisterClipboardFormatW(w!("CanIncludeInClipboardHistory"));
        if IsClipboardFormatAvailable(format).is_ok() && OpenClipboard(None).is_ok() {
            let mut exclude = false;
            if let Ok(handle) = GetClipboardData(format) {
                let data = GlobalLock(HGLOBAL(handle.0));
                if !data.is_null() && GlobalSize(HGLOBAL(handle.0)) >= 4 {
                    exclude = std::ptr::read_unaligned(data as *const u32) == 0;
                }
                if !data.is_null() {
                    let _ = GlobalUnlock(HGLOBAL(handle.0));
                }
            }
            let _ = CloseClipboard();
            return exclude;
        }
    }
    false
}

#[cfg(windows)]
fn clipboard_sequence() -> u32 {
    unsafe { GetClipboardSequenceNumber() }
}

#[cfg(target_os = "linux")]
fn clipboard_sequence() -> u32 {
    0
}

#[cfg(windows)]
pub fn start_monitor(app: tauri::AppHandle, state: Arc<ClipboardState>) {
    std::thread::spawn(move || {
        let mut clipboard = match arboard::Clipboard::new() {
            Ok(value) => value,
            Err(error) => {
                eprintln!("Clipboard unavailable: {error}");
                return;
            }
        };
        loop {
            std::thread::sleep(Duration::from_millis(350));
            if app.get_webview_window("main").is_none() {
                break;
            }
            let Ok(_guard) = state.gate.lock() else {
                break;
            };
            let seq = unsafe { GetClipboardSequenceNumber() };
            if seq == state.sequence.load(Ordering::SeqCst) {
                continue;
            }
            if !state.enabled.load(Ordering::SeqCst) || excluded() {
                state.sequence.store(seq, Ordering::SeqCst);
                continue;
            }
            let files = match crate::clipboard_formats::read_files() {
                Ok(files) => files,
                Err(_) => continue,
            };
            let result = if let Some(files) = files {
                tauri::async_runtime::block_on(state.save_files(files))
            } else if let Ok(Some(png)) = crate::clipboard_formats::read_png() {
                tauri::async_runtime::block_on(state.save_png(png))
            } else if let Ok(image) = clipboard.get_image() {
                tauri::async_runtime::block_on(state.save_image(image))
            } else if let Ok(text) = clipboard.get_text() {
                tauri::async_runtime::block_on(state.save_text(&text))
            } else {
                continue;
            }; // A locked clipboard is retried on the next tick.
            if unsafe { GetClipboardSequenceNumber() } == seq {
                state.sequence.store(seq, Ordering::SeqCst);
            }
            if let Err(error) = result {
                eprintln!("Clipboard capture failed: {error}");
            } else {
                let _ = app.emit("clipboard-changed", ());
            }
        }
    });
}

#[cfg(target_os = "linux")]
pub fn start_monitor(app: tauri::AppHandle, state: Arc<ClipboardState>) {
    std::thread::spawn(move || {
        let mut clipboard = match arboard::Clipboard::new() {
            Ok(value) => value,
            Err(error) => {
                eprintln!("Clipboard unavailable: {error}");
                return;
            }
        };
        let mut previous = None;
        let mut was_enabled = false;
        let mut last_epoch = state.sequence.load(Ordering::SeqCst);
        loop {
            std::thread::sleep(Duration::from_millis(500));
            if app.get_webview_window("main").is_none() {
                break;
            }
            let Ok(_guard) = state.gate.lock() else { break };
            let epoch = state.sequence.load(Ordering::SeqCst);
            if epoch != last_epoch {
                previous = None;
                was_enabled = false;
                last_epoch = epoch;
            }
            let enabled = state.enabled.load(Ordering::SeqCst);
            if !enabled {
                was_enabled = false;
                previous = None;
                continue;
            }
            let content = if let Ok(Some(files)) = crate::clipboard_formats::read_files() {
                if files.is_empty() {
                    continue;
                }
                let bytes = serde_json::to_vec(&files).unwrap_or_default();
                Some(("files", bytes, Some(files), None, None))
            } else if let Ok(Some(png)) = crate::clipboard_formats::read_png() {
                Some(("image", png.clone(), None, None, Some(png)))
            } else if let Ok(image) = clipboard.get_image() {
                Some(("image", image.bytes.to_vec(), None, Some(image), None))
            } else if let Ok(text) = clipboard.get_text() {
                Some(("text", text.as_bytes().to_vec(), None, None, None))
            } else {
                None
            };
            let Some((kind, bytes, files, image, png)) = content else {
                continue;
            };
            let mut digest = Sha256::new();
            digest.update(kind);
            digest.update(&bytes);
            let hash: [u8; 32] = digest.finalize().into();
            if !was_enabled {
                was_enabled = true;
                previous = Some(hash);
                continue;
            }
            if previous == Some(hash) {
                continue;
            }
            let result = if let Some(files) = files {
                tauri::async_runtime::block_on(state.save_files(files))
            } else if let Some(png) = png {
                tauri::async_runtime::block_on(state.save_png(png))
            } else if let Some(image) = image {
                tauri::async_runtime::block_on(state.save_image(image))
            } else {
                tauri::async_runtime::block_on(state.save_text(&String::from_utf8_lossy(&bytes)))
            };
            if let Err(error) = result {
                eprintln!("Clipboard capture failed: {error}");
            } else {
                previous = Some(hash);
                let _ = app.emit("clipboard-changed", ());
            }
        }
    });
}

#[tauri::command]
pub async fn list_clipboard(
    state: tauri::State<'_, Arc<ClipboardState>>,
    search: String,
    pinned_only: Option<bool>,
) -> Result<History, String> {
    if pinned_only.unwrap_or(false) {
        state.view(&search, true).await
    } else {
        state.list(&search).await
    }
}
#[tauri::command]
pub async fn set_clipboard_enabled(
    state: tauri::State<'_, Arc<ClipboardState>>,
    enabled: bool,
) -> Result<(), String> {
    sqlx::query("INSERT INTO clipboard_settings(id,enabled) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled").bind(enabled).execute(&state.pool).await.map_err(|e|e.to_string())?;
    let _guard = state.gate.lock().map_err(|_| "Буфер занят")?;
    #[cfg(windows)]
    state.sequence.store(clipboard_sequence(), Ordering::SeqCst);
    #[cfg(target_os = "linux")]
    state.sequence.fetch_add(1, Ordering::SeqCst);
    state.enabled.store(enabled, Ordering::SeqCst);
    Ok(())
}
#[tauri::command]
pub async fn pin_clipboard(
    state: tauri::State<'_, Arc<ClipboardState>>,
    id: i64,
    pinned: bool,
) -> Result<(), String> {
    let mut tx = state.pool.begin().await.map_err(|e| e.to_string())?;
    if pinned {
        let count: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM clipboard_history WHERE pinned=1 AND id!=?")
                .bind(id)
                .fetch_one(&mut *tx)
                .await
                .map_err(|e| e.to_string())?;
        let bytes:i64=sqlx::query_scalar("SELECT COALESCE(SUM(COALESCE(length(payload),0)+COALESCE(length(CAST(text AS BLOB)),0)),0) FROM clipboard_history WHERE pinned=1 OR id=?").bind(id).fetch_one(&mut *tx).await.map_err(|e|e.to_string())?;
        if count >= 32 || bytes > PIN_BYTES {
            return Err("В закреплённом можно хранить до 32 записей и 32 МБ.".into());
        }
    }
    let result = sqlx::query("UPDATE clipboard_history SET pinned=? WHERE id=?")
        .bind(pinned)
        .bind(id)
        .execute(&mut *tx)
        .await
        .map_err(|e| e.to_string())?;
    if result.rows_affected() == 0 {
        return Err("Запись уже удалена".into());
    }
    tx.commit().await.map_err(|e| e.to_string())
}
#[tauri::command]
pub async fn delete_clipboard(
    state: tauri::State<'_, Arc<ClipboardState>>,
    id: i64,
) -> Result<(), String> {
    sqlx::query("DELETE FROM clipboard_history WHERE id=?")
        .bind(id)
        .execute(&state.pool)
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}
#[tauri::command]
pub async fn copy_clipboard_entry(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<ClipboardState>>,
    target: tauri::State<'_, Arc<crate::platform::PasteTarget>>,
    id: i64,
) -> Result<bool, String> {
    let row: (String, Option<String>, Option<Vec<u8>>) =
        sqlx::query_as("SELECT kind,text,payload FROM clipboard_history WHERE id=?")
            .bind(id)
            .fetch_optional(&state.pool)
            .await
            .map_err(|e| e.to_string())?
            .ok_or("Запись уже удалена")?;
    let state = state.inner().clone();
    let target = target.inner().clone();
    #[cfg(windows)]
    let owner = window.hwnd().map_err(|e| e.to_string())?.0 as isize;
    #[cfg(target_os = "linux")]
    let owner = 0;
    #[cfg(target_os = "linux")]
    let _ = window;
    tauri::async_runtime::spawn_blocking(move || {
        let _guard = state.gate.lock().map_err(|_| "Буфер занят")?;
        let mut clipboard = arboard::Clipboard::new().map_err(|e| e.to_string())?;
        if row.0 == "text" {
            clipboard
                .set_text(row.1.unwrap_or_default())
                .map_err(|e| e.to_string())?;
        } else if row.0 == "files" {
            let paths: Vec<String> = serde_json::from_slice(&row.2.ok_or("Нет списка файлов")?)
                .map_err(|e| e.to_string())?;
            crate::clipboard_formats::write_files(owner, &paths)?;
        } else if row.0 == "image" {
            let image = image::load_from_memory(&row.2.ok_or("Нет данных картинки")?)
                .map_err(|e| e.to_string())?
                .to_rgba8();
            clipboard
                .set_image(arboard::ImageData {
                    width: image.width() as usize,
                    height: image.height() as usize,
                    bytes: Cow::Owned(image.into_raw()),
                })
                .map_err(|e| e.to_string())?;
        } else {
            return Err("Неизвестный формат записи".into());
        }
        #[cfg(windows)]
        state.sequence.store(clipboard_sequence(), Ordering::SeqCst);
        #[cfg(target_os = "linux")]
        state.sequence.fetch_add(1, Ordering::SeqCst);
        #[cfg(windows)]
        target.prepare()?;
        Ok::<(), String>(())
    })
    .await
    .map_err(|e| e.to_string())??;
    #[cfg(windows)]
    return Ok(true);
    #[cfg(target_os = "linux")]
    return Ok(target.prepare().await);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn recording_requires_opt_in_and_preserves_an_existing_choice() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("clipboard.sqlite3");
        let state = ClipboardState::open(&path).await.unwrap();
        assert!(!state.summary().await.unwrap().0);
        sqlx::query("INSERT INTO clipboard_settings(id,enabled) VALUES(1,1)")
            .execute(&state.pool)
            .await
            .unwrap();
        state.pool.close().await;
        let reopened = ClipboardState::open(&path).await.unwrap();
        assert!(reopened.summary().await.unwrap().0);
        reopened.pool.close().await;
    }

    #[tokio::test]
    async fn file_groups_keep_exact_paths_photo_preview_and_search_after_restart() {
        let temp = tempfile::tempdir().unwrap();
        let photo = temp.path().join("Фото Петербург.png");
        RgbaImage::from_pixel(4, 3, image::Rgba([31, 84, 120, 255]))
            .save(&photo)
            .unwrap();
        let document = temp.path().join("План.txt");
        std::fs::write(&document, "Local test document").unwrap();
        let paths = vec![
            photo.to_string_lossy().into_owned(),
            document.to_string_lossy().into_owned(),
        ];
        let db = temp.path().join("history.sqlite3");
        let state = ClipboardState::open(&db).await.unwrap();
        state.save_files(paths.clone()).await.unwrap();
        state.save_files(paths.clone()).await.unwrap();
        let found = state.list("ПЕТЕРБУРГ").await.unwrap().entries;
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].kind, "files");
        assert_eq!(found[0].files.len(), 2);
        assert_eq!(found[0].files[0].path, paths[0]);
        assert!(found[0]
            .thumbnail
            .as_deref()
            .unwrap()
            .starts_with("data:image/png;base64,"));
        sqlx::query("UPDATE clipboard_history SET pinned=1")
            .execute(&state.pool)
            .await
            .unwrap();
        state.pool.close().await;
        let state = ClipboardState::open(&db).await.unwrap();
        assert!(state.list("план").await.unwrap().entries[0].pinned);
        assert_eq!(state.summary().await.unwrap(), (false, 1, 1));
        state.enabled.store(false, Ordering::SeqCst);
        assert_eq!(state.summary().await.unwrap(), (false, 1, 1));
        std::fs::remove_file(&document).unwrap();
        assert!(crate::clipboard_formats::write_files(0, &paths)
            .unwrap_err()
            .contains("перемещён"));
    }

    #[tokio::test]
    async fn native_png_only_payload_is_stored_as_an_image() {
        let temp = tempfile::tempdir().unwrap();
        let state = ClipboardState::open(&temp.path().join("history.sqlite3"))
            .await
            .unwrap();
        let mut png = Cursor::new(Vec::new());
        DynamicImage::ImageRgba8(RgbaImage::from_pixel(8, 6, image::Rgba([10, 80, 150, 255])))
            .write_to(&mut png, ImageFormat::Png)
            .unwrap();
        state.save_png(png.into_inner()).await.unwrap();
        let row = state.list("").await.unwrap().entries.remove(0);
        assert_eq!(row.kind, "image");
        assert_eq!((row.width, row.height), (Some(8), Some(6)));
    }

    #[tokio::test]
    async fn unicode_search_dedup_and_exact_text_survive_restart() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("clipboard.sqlite3");
        let state = ClipboardState::open(&path).await.unwrap();
        state.save_text("Привет\n  Мир 🌊").await.unwrap();
        state.save_text("other").await.unwrap();
        state.save_text("Привет\n  Мир 🌊").await.unwrap();
        assert_eq!(state.list("").await.unwrap().entries.len(), 2);
        let found = state.list("ПРИВЕТ").await.unwrap();
        assert_eq!(found.entries.len(), 1);
        assert_eq!(found.entries[0].text.as_deref(), Some("Привет\n  Мир 🌊"));
        state.pool.close().await;
        let state = ClipboardState::open(&path).await.unwrap();
        assert_eq!(state.list("МИР").await.unwrap().entries.len(), 1);
    }

    #[tokio::test]
    async fn pruning_preserves_pins_and_limits_unpinned_history() {
        let temp = tempfile::tempdir().unwrap();
        let state = ClipboardState::open(&temp.path().join("history.sqlite3"))
            .await
            .unwrap();
        state.save_text("pinned").await.unwrap();
        sqlx::query("UPDATE clipboard_history SET pinned=1")
            .execute(&state.pool)
            .await
            .unwrap();
        for i in 0..105 {
            state.save_text(&format!("entry {i}")).await.unwrap();
        }
        let stored: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM clipboard_history")
            .fetch_one(&state.pool)
            .await
            .unwrap();
        assert_eq!(stored, 101);
        let entries = state.list("").await.unwrap().entries;
        assert_eq!(entries.len(), 9);
        assert_eq!(entries[0].text.as_deref(), Some("entry 104"));
        assert_eq!(entries[8].text.as_deref(), Some("entry 96"));
        assert!(state.list("pinned").await.unwrap().entries.is_empty());
        let pinned = state.view("pinned", true).await.unwrap().entries;
        assert_eq!(pinned.len(), 1);
        assert_eq!(pinned[0].text.as_deref(), Some("pinned"));
        assert!(pinned[0].pinned);
        assert_eq!(state.summary().await.unwrap(), (false, 9, 1));
    }

    #[tokio::test]
    async fn image_payload_and_preview_roundtrip() {
        let temp = tempfile::tempdir().unwrap();
        let state = ClipboardState::open(&temp.path().join("history.sqlite3"))
            .await
            .unwrap();
        let pixels = [31, 84, 120, 255].repeat(12);
        state
            .save_image(arboard::ImageData {
                width: 4,
                height: 3,
                bytes: Cow::Borrowed(&pixels),
            })
            .await
            .unwrap();
        let entries = state.list("КАРТИНКА").await.unwrap().entries;
        assert_eq!(entries.len(), 1);
        assert_eq!((entries[0].width, entries[0].height), (Some(4), Some(3)));
        assert!(entries[0]
            .thumbnail
            .as_ref()
            .unwrap()
            .starts_with("data:image/png;base64,"));
        let png: Vec<u8> = sqlx::query_scalar("SELECT payload FROM clipboard_history")
            .fetch_one(&state.pool)
            .await
            .unwrap();
        assert_eq!(
            image::load_from_memory(&png).unwrap().to_rgba8().as_raw(),
            &pixels
        );
    }

    #[tokio::test]
    async fn empty_and_oversized_text_is_not_collected() {
        let temp = tempfile::tempdir().unwrap();
        let state = ClipboardState::open(&temp.path().join("history.sqlite3"))
            .await
            .unwrap();
        state.save_text(" \n ").await.unwrap();
        state.save_text(&"x".repeat(256 * 1024 + 1)).await.unwrap();
        assert!(state.list("").await.unwrap().entries.is_empty());
    }
}

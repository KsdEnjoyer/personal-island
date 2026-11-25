use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use task_core::{NewTask, Task, TaskPatch, TaskStore};
use tauri::{Emitter, LogicalSize, Manager, PhysicalPosition, Position, Size};
#[cfg(windows)]
mod audio_reactivity;
#[cfg(target_os = "linux")]
#[path = "audio_reactivity_linux.rs"]
mod audio_reactivity;
mod clipboard;
#[cfg(windows)]
mod clipboard_formats;
#[cfg(target_os = "linux")]
#[path = "clipboard_formats_linux.rs"]
mod clipboard_formats;
mod focus_timer;
#[cfg(target_os = "linux")]
mod gnome_island;
#[cfg(windows)]
mod keyboard;
#[cfg(target_os = "linux")]
#[path = "keyboard_linux.rs"]
mod keyboard;
#[cfg(windows)]
mod media;
#[cfg(target_os = "linux")]
#[path = "media_linux.rs"]
mod media;
#[cfg(windows)]
mod music_start;
mod notes;
#[cfg(windows)]
mod platform;
#[cfg(target_os = "linux")]
#[path = "platform_linux.rs"]
mod platform;
#[cfg(target_os = "linux")]
mod portal_identity_linux;
mod preferences;
#[cfg(windows)]
mod volume;
#[cfg(target_os = "linux")]
#[path = "volume_linux.rs"]
mod volume;
mod weather;
#[cfg(target_os = "linux")]
mod x11_linux;
use platform::PasteTarget;
use std::sync::Arc;

// Transparent room for the shoulders, liquid edge and its shadow.
const COLLAPSED_W: f64 = 480.0;
const COLLAPSED_H: f64 = 196.0;
const EXPANDED_W: f64 = 960.0;
const EXPANDED_H: f64 = 640.0;

#[derive(Default)]
struct IslandPresentation {
    generation: AtomicU64,
    ready: AtomicBool,
    compact_mode: AtomicU32,
    overlay_open: AtomicBool,
    reminder_active: AtomicBool,
    review_active: AtomicBool,
    portrait: AtomicBool,
    panel_height: AtomicU32,
}

#[tauri::command]
fn set_island_appearance(app: tauri::AppHandle, portrait: bool) {
    app.state::<IslandPresentation>()
        .portrait
        .store(portrait, Ordering::SeqCst);
}

#[tauri::command]
fn register_island_shortcut(app: tauri::AppHandle) -> Result<u32, String> {
    // The frontend subscribes before this command, including after a dev reload.

    let state = app.state::<IslandPresentation>();
    state.ready.store(true, Ordering::SeqCst);
    reveal_compact(&app, "startup")?;
    Ok(state.panel_height.load(Ordering::SeqCst))
}

#[tauri::command]
fn toggle_island_shortcut(app: tauri::AppHandle) -> Result<(), String> {
    if !app
        .state::<IslandPresentation>()
        .ready
        .load(Ordering::SeqCst)
    {
        return Ok(());
    }
    // The frontend knows whether the island is already fading out. Let it
    // choose hide/show so another press can also reverse that transition.
    app.emit("island-toggle", ()).map_err(|e| e.to_string())
}

#[tauri::command]
fn reveal_island_shortcut(app: tauri::AppHandle) -> Result<(), String> {
    reveal_compact(&app, "manual")
}

fn reveal_compact(app: &tauri::AppHandle, reason: &str) -> Result<(), String> {
    let Some(window) = app.get_webview_window("main") else {
        return Ok(());
    };
    let state = app.state::<IslandPresentation>();
    if !state.ready.load(Ordering::SeqCst)
        || (reason != "manual" && state.reminder_active.load(Ordering::SeqCst))
        || (reason == "track"
            && state.review_active.load(Ordering::SeqCst)
            && window.is_visible().map_err(|e| e.to_string())?)
        || (reason != "manual"
            && window.is_visible().map_err(|e| e.to_string())?
            && window.inner_size().map_err(|e| e.to_string())?.width as f64
                / window.scale_factor().unwrap_or(1.0)
                > 500.0)
    {
        return Ok(());
    }
    state
        .compact_mode
        .store(if reason == "track" { 1 } else { 0 }, Ordering::SeqCst);
    state.overlay_open.store(false, Ordering::SeqCst);
    state.reminder_active.store(false, Ordering::SeqCst);
    state
        .review_active
        .store(matches!(reason, "startup" | "hourly"), Ordering::SeqCst);
    app.state::<Arc<PasteTarget>>().remember_foreground();
    let generation = state.generation.fetch_add(1, Ordering::SeqCst) + 1;
    // Reset the native bounds before showing, so a previous dashboard never flashes.
    window.set_focusable(false).map_err(|e| e.to_string())?;
    resize_and_anchor(&window, false).map_err(|e| e.to_string())?;
    window.show().map_err(|e| e.to_string())?;
    #[cfg(target_os = "linux")]
    window
        .set_ignore_cursor_events(state.panel_height.load(Ordering::SeqCst) != 0)
        .map_err(|e| e.to_string())?;
    window
        .emit(
            "island-reveal",
            serde_json::json!({"generation":generation,"reason":reason}),
        )
        .map_err(|e| e.to_string())
}

fn next_review_boundary(now_ms: i64, period_ms: i64) -> i64 {
    (now_ms.div_euclid(period_ms) + 1) * period_ms
}
fn review_is_due(boundary: i64, now_ms: i64, last: Option<i64>, period_ms: i64) -> bool {
    now_ms >= boundary
        && now_ms - boundary <= 5000.min(period_ms / 2)
        && last.is_none_or(|previous| boundary > previous)
}
fn next_local_review_boundary(now_ms: i64, period_ms: i64, offset_seconds: i32) -> i64 {
    let offset = i64::from(offset_seconds) * 1000;
    let local = now_ms + offset;
    let midnight = local.div_euclid(86_400_000) * 86_400_000;
    (midnight + next_review_boundary(local - midnight, period_ms)).min(midnight + 86_400_000)
        - offset
}
async fn periodic_reveal_loop(app: tauri::AppHandle) {
    let mut last = None;
    loop {
        let preferences = app.state::<preferences::Preferences>();
        let minutes = preferences
            .value
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .review_interval_minutes;
        if minutes == 0 {
            tokio::select! {
                _ = preferences.changed.notified() => {},
                _ = tokio::time::sleep(std::time::Duration::from_secs(15)) => {},
            }
            if app.get_webview_window("main").is_none() {
                break;
            }
            continue;
        }
        let seconds = u64::from(minutes) * 60;
        // Test acceleration never overrides the user's off switch.
        #[cfg(debug_assertions)]
        let seconds = std::env::var("PERSONAL_ISLAND_QA_REVEAL_SECONDS")
            .ok()
            .and_then(|value| value.parse::<u64>().ok())
            .filter(|value| *value > 0 && *value <= 1800)
            .unwrap_or(seconds);
        let period_ms = seconds as i64 * 1000;
        let now = chrono::Utc::now().timestamp_millis();
        let boundary = next_local_review_boundary(
            now,
            period_ms,
            chrono::Local::now().offset().local_minus_utc(),
        );
        // Recheck wall time periodically, including after sleep or clock changes.
        tokio::select! {
            _ = preferences.changed.notified() => continue,
            _ = tokio::time::sleep(std::time::Duration::from_millis((boundary - now).min(15000) as u64)) => {},
        }
        if preferences
            .value
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .review_interval_minutes
            != minutes
        {
            continue;
        }
        if app.get_webview_window("main").is_none() {
            break;
        }
        if review_is_due(
            boundary,
            chrono::Utc::now().timestamp_millis(),
            last,
            period_ms,
        ) {
            last = Some(boundary);
            if let Err(error) = reveal_compact(&app, "hourly") {
                eprintln!("Could not show periodic island: {error}");
            }
        }
    }
}

#[tauri::command]
fn set_island_shortcut_editing(window: tauri::WebviewWindow, editing: bool) -> Result<(), String> {
    let editing_here = editing && window.is_focused().map_err(|e| e.to_string())?;
    keyboard::EDITING.store(editing_here, Ordering::Relaxed);
    Ok(())
}

#[tauri::command]
fn set_shortcut_capture(window: tauri::WebviewWindow, capturing: bool) -> Result<(), String> {
    keyboard::CAPTURING.store(
        capturing && window.is_focused().map_err(|e| e.to_string())?,
        Ordering::SeqCst,
    );
    Ok(())
}

#[tauri::command]
fn hide_island(window: tauri::WebviewWindow, generation: u64) -> Result<(), String> {
    if window
        .state::<IslandPresentation>()
        .generation
        .load(Ordering::SeqCst)
        != generation
    {
        return Ok(());
    }
    keyboard::EDITING.store(false, Ordering::Relaxed);
    keyboard::CAPTURING.store(false, Ordering::Relaxed);
    window
        .state::<IslandPresentation>()
        .review_active
        .store(false, Ordering::SeqCst);
    window.hide().map_err(|e| e.to_string())
}

#[tauri::command]
async fn list_tasks(
    store: tauri::State<'_, TaskStore>,
    include_completed: bool,
) -> Result<Vec<Task>, String> {
    store
        .list(include_completed)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn create_task(store: tauri::State<'_, TaskStore>, task: NewTask) -> Result<Task, String> {
    store.create(task).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn complete_task(
    store: tauri::State<'_, TaskStore>,
    id: i64,
    completed: bool,
) -> Result<Task, String> {
    store
        .set_complete(id, completed)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn update_task(
    store: tauri::State<'_, TaskStore>,
    id: i64,
    patch: TaskPatch,
) -> Result<Task, String> {
    store.patch(id, patch).await.map_err(|e| e.to_string())
}

#[tauri::command]
async fn reschedule_task(
    store: tauri::State<'_, TaskStore>,
    id: i64,
    due_at: Option<String>,
    reminder_at: Option<String>,
) -> Result<Task, String> {
    store
        .reschedule(id, due_at, reminder_at)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn delete_task(store: tauri::State<'_, TaskStore>, id: i64) -> Result<(), String> {
    store.delete(id).await.map_err(|e| e.to_string())
}

fn resize_and_anchor(window: &tauri::WebviewWindow, expanded: bool) -> tauri::Result<()> {
    let (w, h) = if expanded {
        dashboard_size(window)?
    } else {
        compact_size(&window.state::<IslandPresentation>())
    };
    anchor_size(window, w, h)
}

fn compact_dimensions(portrait: bool, mode: u32) -> (f64, f64) {
    if portrait && mode == 0 {
        (384.0, 148.0)
    } else {
        (COLLAPSED_W, COLLAPSED_H)
    }
}

fn compact_size(state: &IslandPresentation) -> (f64, f64) {
    compact_dimensions(
        state.portrait.load(Ordering::SeqCst),
        state.compact_mode.load(Ordering::SeqCst),
    )
}

fn dashboard_size(window: &tauri::WebviewWindow) -> tauri::Result<(f64, f64)> {
    let Some(monitor) = window.current_monitor()? else {
        return Ok((EXPANDED_W, EXPANDED_H));
    };
    let area = monitor.work_area().size;
    let scale = monitor.scale_factor();
    Ok((
        EXPANDED_W.min((area.width as f64 / scale).floor()),
        EXPANDED_H.min((area.height as f64 / scale).floor()),
    ))
}

fn calendar_size(screen_w: f64, screen_h: f64) -> (f64, f64) {
    (
        (screen_w - 32.0).clamp(640.0, 1280.0).floor(),
        (screen_h - 70.0).clamp(420.0, 820.0).floor(),
    )
}

#[cfg(test)]
mod layout_tests {
    #[test]
    fn custom_intervals_follow_local_midnight_in_fractional_timezones() {
        let now = chrono::DateTime::parse_from_rfc3339("2026-11-20T13:04:00+05:45")
            .unwrap()
            .timestamp_millis();
        let next = chrono::DateTime::parse_from_rfc3339("2026-11-20T13:30:00+05:45")
            .unwrap()
            .timestamp_millis();
        assert_eq!(
            super::next_local_review_boundary(now, 45 * 60000, 20700),
            next
        );
        let late = chrono::DateTime::parse_from_rfc3339("2026-11-20T23:59:00+05:45")
            .unwrap()
            .timestamp_millis();
        let midnight = chrono::DateTime::parse_from_rfc3339("2026-11-21T00:00:00+05:45")
            .unwrap()
            .timestamp_millis();
        assert_eq!(
            super::next_local_review_boundary(late, 50 * 60000, 20700),
            midnight
        );
    }
    #[test]
    fn portrait_bounds_are_small_only_for_manual_and_scheduled_overviews() {
        assert_eq!(super::compact_dimensions(true, 0), (384.0, 148.0));
        for (portrait, mode) in [(false, 0), (true, 1), (true, 2)] {
            assert_eq!(super::compact_dimensions(portrait, mode), (480.0, 196.0));
        }
    }

    #[test]
    fn reviews_align_to_half_hours_instead_of_launch_time() {
        let ms = |date: &str| {
            chrono::DateTime::parse_from_rfc3339(date)
                .unwrap()
                .timestamp_millis()
        };
        for (now, next) in [
            ("2026-11-16T13:04:11.123+03:00", "2026-11-16T13:30:00+03:00"),
            ("2026-11-16T13:29:59.999+03:00", "2026-11-16T13:30:00+03:00"),
            ("2026-11-16T13:30:00+03:00", "2026-11-16T14:00:00+03:00"),
            ("2026-11-16T23:59:59.900+03:00", "2026-11-17T00:00:00+03:00"),
        ] {
            assert_eq!(super::next_review_boundary(ms(now), 1800000), ms(next));
        }
    }
    #[test]
    fn reviews_skip_sleep_backlogs_and_duplicate_boundaries() {
        let boundary = 1800000;
        assert!(!super::review_is_due(boundary, boundary - 1, None, 1800000));
        assert!(super::review_is_due(boundary, boundary + 25, None, 1800000));
        assert!(!super::review_is_due(
            boundary,
            boundary + 10 * 60000,
            None,
            1800000
        ));
        assert!(!super::review_is_due(
            boundary,
            boundary + 25,
            Some(boundary),
            1800000
        ));
        assert!(!super::review_is_due(
            boundary,
            boundary + 25,
            Some(boundary + 1800000),
            1800000
        ));
    }
    #[test]
    fn calendar_fits_laptop_scaling_and_leaves_screen_margins() {
        for (width, height) in [
            (1920.0, 1080.0),
            (1536.0, 864.0),
            (1280.0, 720.0),
            (1024.0, 640.0),
            (768.0, 600.0),
        ] {
            let (w, h) = super::calendar_size(width, height);
            assert!(w <= width - 32.0 && h <= height - 70.0);
            assert!(w <= 1280.0 && h <= 820.0);
        }
    }
}

fn anchor_size(window: &tauri::WebviewWindow, w: f64, h: f64) -> tauri::Result<()> {
    window.set_size(Size::Logical(LogicalSize::new(w, h)))?;
    #[cfg(target_os = "linux")]
    if window
        .state::<IslandPresentation>()
        .panel_height
        .load(Ordering::SeqCst)
        != 0
    {
        // The extension anchors the surface to the actual GNOME panel slot.
        return Ok(());
    }
    if let Some(monitor) = window.current_monitor()? {
        let scale = monitor.scale_factor();
        let x =
            monitor.position().x + (monitor.size().width as i32 - (w * scale).round() as i32) / 2;
        #[cfg(target_os = "linux")]
        let y = monitor.work_area().position.y;
        #[cfg(not(target_os = "linux"))]
        let y = monitor.position().y;
        window.set_position(Position::Physical(PhysicalPosition::new(x, y)))?;
    }
    Ok(())
}

#[tauri::command]
fn set_island_expanded(
    window: tauri::WebviewWindow,
    expanded: bool,
    generation: u64,
    calendar: Option<bool>,
) -> Result<(f64, f64), String> {
    if window
        .state::<IslandPresentation>()
        .generation
        .load(Ordering::SeqCst)
        != generation
    {
        let size = window.inner_size().map_err(|e| e.to_string())?;
        let scale = window.scale_factor().map_err(|e| e.to_string())?;
        return Ok((size.width as f64 / scale, size.height as f64 / scale));
    }
    window
        .state::<IslandPresentation>()
        .overlay_open
        .store(false, Ordering::SeqCst);
    let size = if expanded && calendar.unwrap_or(false) {
        if let Some(monitor) = window.current_monitor().map_err(|e| e.to_string())? {
            calendar_size(
                monitor.size().width as f64 / monitor.scale_factor(),
                monitor.size().height as f64 / monitor.scale_factor(),
            )
        } else {
            (1280.0, 820.0)
        }
    } else if expanded {
        dashboard_size(&window).map_err(|e| e.to_string())?
    } else {
        compact_size(&window.state::<IslandPresentation>())
    };
    let panel_height = window
        .state::<IslandPresentation>()
        .panel_height
        .load(Ordering::SeqCst);
    anchor_size(
        &window,
        size.0,
        size.1
            + if expanded {
                f64::from(panel_height)
            } else {
                0.0
            },
    )
    .map_err(|e| e.to_string())?;
    window.set_focusable(expanded).map_err(|e| e.to_string())?;
    #[cfg(target_os = "linux")]
    window
        .set_ignore_cursor_events(panel_height != 0 && !expanded)
        .map_err(|e| e.to_string())?;
    if expanded {
        window.show().map_err(|e| e.to_string())?;
        if panel_height != 0 {
            window.set_focus().map_err(|e| e.to_string())?;
        }
    }
    Ok(size)
}

// Transparent room for the detached volume panel; the canvas body keeps its size.
#[tauri::command]
fn set_island_overlay(
    window: tauri::WebviewWindow,
    generation: u64,
    open: bool,
) -> Result<(), String> {
    let state = window.state::<IslandPresentation>();
    if state.generation.load(Ordering::SeqCst) != generation {
        return Ok(());
    }
    let scale = window.scale_factor().map_err(|e| e.to_string())?;
    let width = window.inner_size().map_err(|e| e.to_string())?.width as f64 / scale;
    if width > 500.0 {
        return Ok(());
    }
    state.overlay_open.store(open, Ordering::SeqCst);
    let base = compact_size(&state);
    window
        .set_size(Size::Logical(LogicalSize::new(
            base.0,
            if open { 264.0 } else { base.1 },
        )))
        .map_err(|e| e.to_string())
}

#[derive(serde::Serialize)]
struct WidgetSummary {
    notes: i64,
    ideas: i64,
    shopping: i64,
    clipboard: i64,
    pinned: i64,
    capturing: bool,
}
#[tauri::command]
async fn get_widget_summary(
    notes: tauri::State<'_, notes::NotesStore>,
    clipboard: tauri::State<'_, Arc<clipboard::ClipboardState>>,
) -> Result<WidgetSummary, String> {
    let ((notes, ideas, shopping), (capturing, clipboard, pinned)) =
        tokio::try_join!(notes.summary(), clipboard.summary())?;
    Ok(WidgetSummary {
        notes,
        ideas,
        shopping,
        clipboard,
        pinned,
        capturing,
    })
}

#[tauri::command]
fn exit_app(app: tauri::AppHandle) {
    app.exit(0);
}

#[tauri::command]
fn get_platform_capabilities() -> serde_json::Value {
    #[cfg(windows)]
    let shortcut_mode = "windows";
    #[cfg(target_os = "linux")]
    let shortcut_mode = if x11_linux::native_session() {
        "x11"
    } else {
        "portal"
    };
    #[cfg(target_os = "linux")]
    let shortcut_label = keyboard::shortcut_label();
    #[cfg(not(target_os = "linux"))]
    let shortcut_label = Some("Ё / `");
    serde_json::json!({
        "automaticPaste": cfg!(windows) || cfg!(target_os = "linux"),
        "shortcutMode": shortcut_mode,
        "musicAppBinding": cfg!(target_os = "linux"),
        "shortcutLabel": shortcut_label,
    })
}

#[tauri::command]
async fn paste_to_previous_window(
    target: tauri::State<'_, Arc<PasteTarget>>,
) -> Result<(), String> {
    let target = target.inner().clone();
    #[cfg(windows)]
    {
        tauri::async_runtime::spawn_blocking(move || target.paste())
            .await
            .map_err(|e| e.to_string())?
    }
    #[cfg(target_os = "linux")]
    {
        target.paste().await
    }
}

// Native events keep the five-second lease reliable even when an unfocused
// WebView throttles JS timers or retains a stale CSS hover after window.show().
async fn pointer_loop(app: tauri::AppHandle) {
    let mut ticker = tokio::time::interval(std::time::Duration::from_millis(250));
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        ticker.tick().await;
        #[cfg(windows)]
        app.state::<Arc<PasteTarget>>().remember_foreground();
        let Some(window) = app.get_webview_window("main") else {
            break;
        };
        focus_timer::check(&app, &window);
        if window.is_visible().ok() != Some(true) {
            continue;
        }
        if let (Ok(cursor), Ok(origin), Ok(size), Ok(scale)) = (
            window.cursor_position(),
            window.outer_position(),
            window.inner_size(),
            window.scale_factor(),
        ) {
            let x = (cursor.x - origin.x as f64) / scale;
            let y = (cursor.y - origin.y as f64) / scale;
            let w = size.width as f64 / scale;
            let expanded = w > 500.0;
            let mode = app
                .state::<IslandPresentation>()
                .compact_mode
                .load(Ordering::SeqCst);
            let body = if expanded {
                w - 56.0
            } else if mode == 1 {
                360.0
            } else {
                272.0
            };
            let bottom = if expanded {
                size.height as f64 / scale - 34.0
            } else if app
                .state::<IslandPresentation>()
                .overlay_open
                .load(Ordering::SeqCst)
            {
                248.0
            } else if mode == 2 {
                88.0
            } else if mode == 1 {
                100.0
            } else if mode == 0
                && app
                    .state::<IslandPresentation>()
                    .portrait
                    .load(Ordering::SeqCst)
            {
                130.0
            } else {
                120.0
            };
            let inside = x >= (w - body) / 2.0 - 24.0
                && x <= (w + body) / 2.0 + 24.0
                && y >= 0.0
                && y <= bottom;
            let _ = window.emit("island-pointer", inside);
        }
    }
}

async fn notification_loop(app: tauri::AppHandle, store: TaskStore) {
    // Missed reminders are reviewed at startup and every half-hour, including
    // ones previously displayed. Keep punctual bells for new reminders only.
    let started_at = chrono::Utc::now().to_rfc3339();
    let mut ticker = tokio::time::interval(std::time::Duration::from_secs(5));
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        ticker.tick().await;
        if !app
            .state::<IslandPresentation>()
            .ready
            .load(Ordering::SeqCst)
        {
            continue;
        }
        match store.due_notifications_since(Some(&started_at)).await {
            Ok(tasks) => {
                if !tasks.is_empty() {
                    if let Some(window) = app.get_webview_window("main") {
                        if let Err(error) = window.emit("island-reminders", tasks) {
                            eprintln!("Could not deliver island reminders: {error}");
                        }
                    }
                }
            }
            Err(e) => eprintln!("Scheduler error: {e}"),
        }
    }
}

#[derive(serde::Serialize)]
struct ReminderPresentation {
    generation: u64,
    expanded: bool,
}

#[tauri::command]
fn show_reminder_island(
    app: tauri::AppHandle,
    generation: u64,
) -> Result<ReminderPresentation, String> {
    let window = app
        .get_webview_window("main")
        .ok_or("Island window is unavailable")?;
    let state = app.state::<IslandPresentation>();
    if !state.ready.load(Ordering::SeqCst) {
        return Err("Island is not ready".into());
    }
    if state.generation.load(Ordering::SeqCst) != generation {
        return Err("Island presentation changed".into());
    }
    let expanded = window.is_visible().map_err(|e| e.to_string())?
        && window.inner_size().map_err(|e| e.to_string())?.width as f64
            / window.scale_factor().unwrap_or(1.0)
            > 500.0;
    state.reminder_active.store(true, Ordering::SeqCst);
    state.review_active.store(false, Ordering::SeqCst);
    let generation = if expanded {
        state.generation.load(Ordering::SeqCst)
    } else {
        state.compact_mode.store(2, Ordering::SeqCst);
        state.overlay_open.store(false, Ordering::SeqCst);
        let generation = state.generation.fetch_add(1, Ordering::SeqCst) + 1;
        app.state::<Arc<PasteTarget>>().remember_foreground();
        window.set_focusable(false).map_err(|e| e.to_string())?;
        resize_and_anchor(&window, false).map_err(|e| e.to_string())?;
        window.show().map_err(|e| e.to_string())?;
        generation
    };
    Ok(ReminderPresentation {
        generation,
        expanded,
    })
}

#[tauri::command]
async fn acknowledge_island_reminder(
    window: tauri::WebviewWindow,
    store: tauri::State<'_, TaskStore>,
    generation: u64,
    id: i64,
    reminder_at: String,
) -> Result<bool, String> {
    let state = window.state::<IslandPresentation>();
    if state.generation.load(Ordering::SeqCst) != generation
        || !state.reminder_active.load(Ordering::SeqCst)
        || !window.is_visible().map_err(|e| e.to_string())?
    {
        return Ok(false);
    }
    store
        .mark_reminder_presented(id, &reminder_at)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn acknowledge_island_review(
    window: tauri::WebviewWindow,
    store: tauri::State<'_, TaskStore>,
    generation: u64,
    id: i64,
    reminder_at: String,
) -> Result<bool, String> {
    let state = window.state::<IslandPresentation>();
    if state.generation.load(Ordering::SeqCst) != generation
        || !state.review_active.load(Ordering::SeqCst)
        || !window.is_visible().map_err(|e| e.to_string())?
        || window.inner_size().map_err(|e| e.to_string())?.width as f64
            / window.scale_factor().unwrap_or(1.0)
            > 500.0
    {
        return Ok(false);
    }
    store
        .mark_reminder_presented(id, &reminder_at)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn finish_island_reminder(window: tauri::WebviewWindow, generation: u64) {
    let state = window.state::<IslandPresentation>();
    if state.generation.load(Ordering::SeqCst) == generation {
        state.reminder_active.store(false, Ordering::SeqCst);
    }
}

pub fn run() {
    tauri::Builder::default()
        .manage(Arc::new(audio_reactivity::AudioReactivity::default()))
        .manage(media::MediaPreference::default())
        .manage(media::MediaNotifications::default())
        .manage(IslandPresentation::default())
        .manage(focus_timer::FocusTimer::default())
        .manage(Arc::new(PasteTarget::default()))
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            let _ = reveal_compact(app, "manual");
        }))
        .on_window_event(|_, event| {
            if matches!(event, tauri::WindowEvent::Focused(false)) {
                keyboard::EDITING.store(false, Ordering::Relaxed);
                keyboard::CAPTURING.store(false, Ordering::Relaxed);
            }
        })
        .setup(|app| {
            audio_reactivity::start(app.handle().clone());
            keyboard::start(app.handle().clone())?;
            let store = tauri::async_runtime::block_on(TaskStore::open_default())?;
            let settings = preferences::Preferences::load(
                task_core::default_db_path()?.with_file_name("widget-settings.json"),
            )?;
            {
                let mut value = settings.value.lock().unwrap_or_else(|e| e.into_inner());
                if let Err(error) =
                    keyboard::configure(value.shortcut.clone(), value.suppress_shortcut_character)
                {
                    value.shortcut = preferences::Shortcut::default();
                    #[cfg(windows)]
                    keyboard::configure(value.shortcut.clone(), value.suppress_shortcut_character)?;
                    #[cfg(target_os = "linux")]
                    let _ = keyboard::configure(
                        value.shortcut.clone(),
                        value.suppress_shortcut_character,
                    );
                    value.shortcut_error = Some(format!(
                        "Не удалось назначить сохранённое сочетание: {error}"
                    ));
                }
            }
            app.manage(settings);
            app.manage(weather::WeatherService::new(
                task_core::default_db_path()?.with_file_name("weather.json"),
            )?);
            let clipboard_path = task_core::default_db_path()?.with_file_name("clipboard.sqlite3");
            let clipboard = Arc::new(tauri::async_runtime::block_on(
                clipboard::ClipboardState::open(&clipboard_path),
            )?);
            app.manage(clipboard.clone());
            clipboard::start_monitor(app.handle().clone(), clipboard);
            app.manage(store.clone());
            app.manage(tauri::async_runtime::block_on(notes::NotesStore::open(
                &task_core::default_db_path()?.with_file_name("notes.sqlite3"),
            ))?);
            if let Some(window) = app.get_webview_window("main") {
                resize_and_anchor(&window, false)?;
            }
            #[cfg(target_os = "linux")]
            tauri::async_runtime::spawn(gnome_island::serve(app.handle().clone()));
            tauri::async_runtime::spawn(notification_loop(app.handle().clone(), store));
            tauri::async_runtime::spawn(media::watch(app.handle().clone()));
            tauri::async_runtime::spawn(pointer_loop(app.handle().clone()));
            tauri::async_runtime::spawn(periodic_reveal_loop(app.handle().clone()));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            list_tasks,
            notes::list_notes,
            notes::save_note,
            notes::delete_note,
            create_task,
            complete_task,
            update_task,
            reschedule_task,
            delete_task,
            set_island_expanded,
            set_island_appearance,
            set_island_overlay,
            get_widget_summary,
            preferences::get_widget_settings,
            preferences::set_widget_settings,
            set_shortcut_capture,
            #[cfg(target_os = "linux")]
            keyboard::configure_portal_shortcuts,
            register_island_shortcut,
            focus_timer::set_focus_timer_deadline,
            toggle_island_shortcut,
            reveal_island_shortcut,
            set_island_shortcut_editing,
            hide_island,
            show_reminder_island,
            acknowledge_island_reminder,
            acknowledge_island_review,
            finish_island_reminder,
            clipboard::list_clipboard,
            clipboard::set_clipboard_enabled,
            clipboard::pin_clipboard,
            clipboard::delete_clipboard,
            clipboard::copy_clipboard_entry,
            paste_to_previous_window,
            media::get_media_state,
            media::media_command,
            media::seek_media,
            volume::player_volume,
            audio_reactivity::set_audio_reactivity,
            audio_reactivity::get_audio_reactivity,
            media::open_yandex_music,
            media::start_yandex_music,
            #[cfg(target_os = "linux")]
            media::open_spotify,
            #[cfg(target_os = "linux")]
            media::start_spotify,
            weather::get_weather,
            weather::open_weather_source,
            exit_app,
            get_platform_capabilities
        ])
        .run(tauri::generate_context!())
        .expect("Failed to launch Personal Island");
}

//! Direct X11 shortcut and paste for desktops without keyboard portals.
use std::sync::atomic::Ordering;
use std::time::{Duration, Instant};
use x11rb::{
    connection::Connection,
    protocol::{
        xproto::{
            ConnectionExt as _, GrabMode, InputFocus, MapState, ModMask, KEY_PRESS_EVENT,
            KEY_RELEASE_EVENT,
        },
        xtest::ConnectionExt as _,
        Event,
    },
    rust_connection::RustConnection,
    CURRENT_TIME,
};

const XK_I: u32 = 0x69;
const XK_V: u32 = 0x76;
const XK_CONTROL_L: u32 = 0xffe3;
const XK_NUM_LOCK: u32 = 0xff7f;

pub fn native_session() -> bool {
    std::env::var_os("WAYLAND_DISPLAY").is_none() && std::env::var_os("DISPLAY").is_some()
}

fn connect() -> Result<(RustConnection, usize), String> {
    x11rb::connect(None).map_err(|error| error.to_string())
}

fn keycode(conn: &RustConnection, keysym: u32) -> Result<u8, String> {
    let setup = conn.setup();
    let first = setup.min_keycode;
    let count = setup.max_keycode - first + 1;
    let mapping = conn
        .get_keyboard_mapping(first, count)
        .map_err(|error| error.to_string())?
        .reply()
        .map_err(|error| error.to_string())?;
    mapping
        .keysyms
        .chunks(mapping.keysyms_per_keycode as usize)
        .position(|symbols| symbols.contains(&keysym))
        .map(|index| first + index as u8)
        .ok_or_else(|| format!("Клавиша {keysym:#x} отсутствует в раскладке X11"))
}

fn num_lock_mask(conn: &RustConnection) -> ModMask {
    let Ok(num_lock) = keycode(conn, XK_NUM_LOCK) else {
        return ModMask::default();
    };
    let Ok(Ok(mapping)) = conn.get_modifier_mapping().map(|request| request.reply()) else {
        return ModMask::default();
    };
    if mapping.keycodes_per_modifier() == 0 {
        return ModMask::default();
    }
    mapping
        .keycodes
        .chunks(mapping.keycodes_per_modifier() as usize)
        .position(|codes| codes.contains(&num_lock))
        .map(|index| ModMask::from(1u8 << index))
        .unwrap_or_default()
}

fn grab_shortcut(conn: &RustConnection, root: u32) -> Result<u8, String> {
    let i = keycode(conn, XK_I)?;
    let num_lock = num_lock_mask(conn);
    let base = ModMask::CONTROL | ModMask::M1;
    conn.grab_key(false, root, base, i, GrabMode::ASYNC, GrabMode::ASYNC)
        .map_err(|error| error.to_string())?
        .check()
        .map_err(|_| "Сочетание Ctrl+Alt+I уже занято другим приложением".to_string())?;
    for modifiers in [
        base | ModMask::LOCK,
        base | num_lock,
        base | num_lock | ModMask::LOCK,
    ] {
        if modifiers != base {
            let _ = conn
                .grab_key(false, root, modifiers, i, GrabMode::ASYNC, GrabMode::ASYNC)
                .map_err(|error| error.to_string())?
                .check();
        }
    }
    conn.flush().map_err(|error| error.to_string())?;
    Ok(i)
}

pub fn start_shortcut(app: tauri::AppHandle) {
    std::thread::spawn(move || {
        if let Err(error) = listen_shortcut(app) {
            eprintln!("X11 shortcut unavailable: {error}");
        }
    });
}

fn listen_shortcut(app: tauri::AppHandle) -> Result<(), String> {
    let (conn, screen) = connect()?;
    let root = conn.setup().roots[screen].root;
    let i = grab_shortcut(&conn, root)?;
    let mut last_release = None;
    let mut last_activation = Instant::now() - Duration::from_secs(1);
    loop {
        match conn.wait_for_event().map_err(|error| error.to_string())? {
            Event::KeyPress(event) if event.detail == i => {
                if last_release == Some(event.time)
                    || last_activation.elapsed() < Duration::from_millis(200)
                    || crate::keyboard::EDITING.load(Ordering::Relaxed)
                {
                    continue;
                }
                last_activation = Instant::now();
                let _ = crate::toggle_island_shortcut(app.clone());
            }
            Event::KeyRelease(event) if event.detail == i => last_release = Some(event.time),
            _ => {}
        }
    }
}

pub fn focused_window() -> Option<u32> {
    let (conn, screen) = connect().ok()?;
    let root = conn.setup().roots[screen].root;
    let window = conn.get_input_focus().ok()?.reply().ok()?.focus;
    if window == 0 || window == 1 || window == root {
        return None;
    }
    let attributes = conn.get_window_attributes(window).ok()?.reply().ok()?;
    (attributes.map_state == MapState::VIEWABLE).then_some(window)
}

pub fn paste(window: u32) -> Result<(), String> {
    let (conn, screen) = connect()?;
    let root = conn.setup().roots[screen].root;
    let attributes = conn
        .get_window_attributes(window)
        .map_err(|error| error.to_string())?
        .reply()
        .map_err(|error| error.to_string())?;
    if attributes.map_state != MapState::VIEWABLE {
        return Err("Предыдущее окно больше не открыто; вставь через Ctrl+V".into());
    }
    let control = keycode(&conn, XK_CONTROL_L)?;
    let v = keycode(&conn, XK_V)?;
    conn.set_input_focus(InputFocus::PARENT, window, CURRENT_TIME)
        .map_err(|error| error.to_string())?
        .check()
        .map_err(|error| error.to_string())?;
    let send = |kind, code| -> Result<(), String> {
        conn.xtest_fake_input(kind, code, CURRENT_TIME, root, 0, 0, 0)
            .map_err(|error| error.to_string())?
            .check()
            .map_err(|error| error.to_string())?;
        Ok(())
    };
    send(KEY_PRESS_EVENT, control)?;
    let pressed_v = send(KEY_PRESS_EVENT, v);
    let released_v = send(KEY_RELEASE_EVENT, v);
    let released_control = send(KEY_RELEASE_EVENT, control);
    conn.flush().map_err(|error| error.to_string())?;
    pressed_v.and(released_v).and(released_control)
}

#[cfg(test)]
mod tests {
    use super::*;
    use x11rb::protocol::xproto::{CreateWindowAux, EventMask, WindowClass};
    use x11rb::COPY_DEPTH_FROM_PARENT;

    fn test_window(conn: &RustConnection, root: u32) -> u32 {
        let window = conn.generate_id().unwrap();
        conn.create_window(
            COPY_DEPTH_FROM_PARENT,
            window,
            root,
            0,
            0,
            100,
            100,
            0,
            WindowClass::INPUT_OUTPUT,
            0,
            &CreateWindowAux::new().event_mask(EventMask::KEY_PRESS | EventMask::KEY_RELEASE),
        )
        .unwrap()
        .check()
        .unwrap();
        conn.map_window(window).unwrap().check().unwrap();
        conn.set_input_focus(InputFocus::PARENT, window, CURRENT_TIME)
            .unwrap()
            .check()
            .unwrap();
        conn.flush().unwrap();
        window
    }

    #[test]
    #[ignore = "run under an isolated Xvfb display"]
    fn x11_paste_restores_focus_and_sends_control_v() {
        let (conn, screen) = connect().unwrap();
        let root = conn.setup().roots[screen].root;
        let window = test_window(&conn, root);
        assert_eq!(focused_window(), Some(window));
        paste(window).unwrap();
        let control = keycode(&conn, XK_CONTROL_L).unwrap();
        let v = keycode(&conn, XK_V).unwrap();
        let mut events = Vec::new();
        let deadline = Instant::now() + Duration::from_secs(1);
        while events.len() < 4 && Instant::now() < deadline {
            match conn.poll_for_event().unwrap() {
                Some(Event::KeyPress(event)) => events.push((KEY_PRESS_EVENT, event.detail)),
                Some(Event::KeyRelease(event)) => events.push((KEY_RELEASE_EVENT, event.detail)),
                _ => std::thread::sleep(Duration::from_millis(10)),
            }
        }
        assert_eq!(
            events,
            vec![
                (KEY_PRESS_EVENT, control),
                (KEY_PRESS_EVENT, v),
                (KEY_RELEASE_EVENT, v),
                (KEY_RELEASE_EVENT, control),
            ]
        );
    }

    #[test]
    #[ignore = "run under an isolated Xvfb display"]
    fn x11_grab_receives_control_alt_i() {
        let (conn, screen) = connect().unwrap();
        let root = conn.setup().roots[screen].root;
        let _window = test_window(&conn, root);
        let i = grab_shortcut(&conn, root).unwrap();
        let (sender, _) = connect().unwrap();
        let control = keycode(&sender, XK_CONTROL_L).unwrap();
        let alt = keycode(&sender, 0xffe9).unwrap();
        for (kind, code) in [
            (KEY_PRESS_EVENT, control),
            (KEY_PRESS_EVENT, alt),
            (KEY_PRESS_EVENT, i),
            (KEY_RELEASE_EVENT, i),
            (KEY_RELEASE_EVENT, alt),
            (KEY_RELEASE_EVENT, control),
        ] {
            sender
                .xtest_fake_input(kind, code, CURRENT_TIME, root, 0, 0, 0)
                .unwrap()
                .check()
                .unwrap();
        }
        sender.flush().unwrap();
        let deadline = Instant::now() + Duration::from_secs(1);
        let mut received = false;
        while Instant::now() < deadline {
            match conn.poll_for_event().unwrap() {
                Some(Event::KeyPress(event)) if event.detail == i => {
                    received = true;
                    break;
                }
                _ => std::thread::sleep(Duration::from_millis(10)),
            }
        }
        assert!(received);
    }
}

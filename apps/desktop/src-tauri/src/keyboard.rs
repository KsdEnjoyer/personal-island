//! Single presses type normally; a consecutive double tap removes the first
//! character and consumes the second while keeping both island toggles.
use crate::preferences::Shortcut;
use std::cell::RefCell;
use std::sync::mpsc::{self, Sender};
use std::sync::{
    atomic::{AtomicBool, AtomicU32, Ordering},
    OnceLock,
};
use windows::Win32::{
    Foundation::{LPARAM, LRESULT, WPARAM},
    UI::{
        Input::KeyboardAndMouse::{
            GetAsyncKeyState, GetKeyboardLayout, RegisterHotKey, SendInput, UnregisterHotKey,
            INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, MOD_ALT, MOD_CONTROL,
            MOD_NOREPEAT, MOD_SHIFT, VK_BACK, VK_CONTROL, VK_LWIN, VK_MENU, VK_RWIN,
        },
        WindowsAndMessaging::*,
    },
};
static APP: OnceLock<tauri::AppHandle> = OnceLock::new();
static DOWN: AtomicBool = AtomicBool::new(false);
static CONSUMED: AtomicBool = AtomicBool::new(false);
pub static EDITING: AtomicBool = AtomicBool::new(false);
pub static CAPTURING: AtomicBool = AtomicBool::new(false);
static DEFAULT_ENABLED: AtomicBool = AtomicBool::new(true);
static THREAD: AtomicU32 = AtomicU32::new(0);
static REBIND: OnceLock<Sender<Rebind>> = OnceLock::new();
const REBIND_MESSAGE: u32 = WM_APP + 19;
struct Rebind {
    shortcut: Shortcut,
    reply: Sender<Result<(), String>>,
}

pub fn configure(shortcut: Shortcut) -> Result<(), String> {
    #[cfg(debug_assertions)]
    if std::env::var("PERSONAL_ISLAND_QA_DISABLE_SHORTCUT").as_deref() == Ok("1") {
        return Ok(());
    }
    let (send, receive) = mpsc::channel();
    REBIND
        .get()
        .ok_or("Горячие клавиши ещё не готовы")?
        .send(Rebind {
            shortcut,
            reply: send,
        })
        .map_err(|e| e.to_string())?;
    unsafe {
        PostThreadMessageW(
            THREAD.load(Ordering::SeqCst),
            REBIND_MESSAGE,
            WPARAM(0),
            LPARAM(0),
        )
    }
    .map_err(|e| e.to_string())?;
    receive
        .recv_timeout(std::time::Duration::from_secs(2))
        .map_err(|e| e.to_string())?
}
fn toggle() {
    if let Some(app) = APP.get() {
        let app = app.clone();
        tauri::async_runtime::spawn(async move {
            let _ = crate::toggle_island_shortcut(app);
        });
    }
}
const DOUBLE_TAP_MS: u32 = 1500;
const CLEANUP_TAG: usize = 0x49534c44;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct InputTarget {
    window: isize,
    focus: isize,
    thread: u32,
    layout: isize,
}

#[derive(Default)]
struct DoubleTap {
    previous: Option<(u32, InputTarget)>,
}
impl DoubleTap {
    fn cancel(&mut self) {
        self.previous = None;
    }
    fn press(&mut self, time: u32, target: Option<InputTarget>) -> bool {
        let previous = self.previous.take();
        let Some(target) = target else {
            return false;
        };
        if let Some((then, origin)) = previous {
            if origin == target && time.wrapping_sub(then) <= DOUBLE_TAP_MS {
                return true;
            }
        }
        self.previous = Some((time, target));
        false
    }
}
thread_local! { static DOUBLE_TAP: RefCell<DoubleTap> = RefCell::default(); }

unsafe fn input_target() -> Option<InputTarget> {
    let window = GetForegroundWindow();
    if window.0.is_null() {
        return None;
    }
    let thread = GetWindowThreadProcessId(window, None);
    let mut info = GUITHREADINFO {
        cbSize: std::mem::size_of::<GUITHREADINFO>() as u32,
        ..Default::default()
    };
    if thread == 0 || GetGUIThreadInfo(thread, &mut info).is_err() || info.hwndFocus.0.is_null() {
        return None;
    }
    Some(InputTarget {
        window: window.0 as isize,
        focus: info.hwndFocus.0 as isize,
        thread,
        layout: GetKeyboardLayout(thread).0 as isize,
    })
}

unsafe fn erase_first_press(target: Option<InputTarget>) -> bool {
    // No focus switching or delayed worker: only edit the original input queue.
    if target.is_none() || input_target() != target {
        return false;
    }
    let key = |flags| INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: VK_BACK,
                dwFlags: flags,
                dwExtraInfo: CLEANUP_TAG,
                ..Default::default()
            },
        },
    };
    let inputs = [key(Default::default()), key(KEYEVENTF_KEYUP)];
    SendInput(&inputs, std::mem::size_of::<INPUT>() as i32) == inputs.len() as u32
}

unsafe extern "system" fn observe_mouse(code: i32, message: WPARAM, data: LPARAM) -> LRESULT {
    if code >= 0
        && matches!(
            message.0 as u32,
            WM_LBUTTONDOWN
                | WM_RBUTTONDOWN
                | WM_MBUTTONDOWN
                | WM_XBUTTONDOWN
                | WM_MOUSEWHEEL
                | WM_MOUSEHWHEEL
        )
    {
        DOUBLE_TAP.with(|tap| tap.borrow_mut().cancel());
    }
    CallNextHookEx(None, code, message, data)
}

unsafe extern "system" fn observe(code: i32, key: WPARAM, data: LPARAM) -> LRESULT {
    if code >= 0 {
        let event = &*(data.0 as *const KBDLLHOOKSTRUCT);
        if event.dwExtraInfo == CLEANUP_TAG {
            return CallNextHookEx(None, code, key, data);
        }
        let pressed = key.0 as u32 == WM_KEYDOWN || key.0 as u32 == WM_SYSKEYDOWN;
        if DEFAULT_ENABLED.load(Ordering::Relaxed)
            && (event.scanCode == 0x29 || event.vkCode == 0xC0)
        {
            if pressed {
                if DOWN.swap(true, Ordering::Relaxed) {
                    // Holding the key is typing, not a second tap. Never erase
                    // just one character from an unknown number of repeats.
                    DOUBLE_TAP.with(|tap| tap.borrow_mut().cancel());
                    if CONSUMED.load(Ordering::Relaxed) {
                        return LRESULT(1);
                    }
                    return CallNextHookEx(None, code, key, data);
                }
                let modified = [VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN]
                    .iter()
                    .any(|key| GetAsyncKeyState(key.0 as i32) < 0);
                if !modified
                    && !EDITING.load(Ordering::Relaxed)
                    && !CAPTURING.load(Ordering::Relaxed)
                {
                    let target = input_target();
                    let pair = DOUBLE_TAP.with(|tap| tap.borrow_mut().press(event.time, target));
                    let consumed = pair && erase_first_press(target);
                    CONSUMED.store(consumed, Ordering::Relaxed);
                    toggle();
                    if consumed {
                        return LRESULT(1);
                    }
                } else {
                    DOUBLE_TAP.with(|tap| tap.borrow_mut().cancel());
                }
            } else {
                DOWN.store(false, Ordering::Relaxed);
                if CONSUMED.swap(false, Ordering::Relaxed) {
                    return LRESULT(1);
                }
            }
        } else if pressed {
            DOUBLE_TAP.with(|tap| tap.borrow_mut().cancel());
        }
    }
    CallNextHookEx(None, code, key, data)
}
pub fn start(app: tauri::AppHandle) -> Result<(), String> {
    // Isolated UI suites must not react to the owner's typing in other apps.
    // Release builds always install the pass-through observer.
    #[cfg(debug_assertions)]
    if std::env::var("PERSONAL_ISLAND_QA_DISABLE_SHORTCUT").as_deref() == Ok("1") {
        return Ok(());
    }
    let _ = APP.set(app);
    let (rebind_send, rebind_receive) = mpsc::channel::<Rebind>();
    let _ = REBIND.set(rebind_send);
    let (send, receive) = std::sync::mpsc::sync_channel(1);
    std::thread::spawn(move || unsafe {
        let mut queue = MSG::default();
        let _ = PeekMessageW(&mut queue, None, 0, 0, PM_NOREMOVE);
        THREAD.store(
            windows::Win32::System::Threading::GetCurrentThreadId(),
            Ordering::SeqCst,
        );
        let hook = SetWindowsHookExW(WH_KEYBOARD_LL, Some(observe), None, 0);
        match hook {
            Ok(hook) => {
                let mouse = match SetWindowsHookExW(WH_MOUSE_LL, Some(observe_mouse), None, 0) {
                    Ok(mouse) => mouse,
                    Err(error) => {
                        let _ = UnhookWindowsHookEx(hook);
                        let _ = send.send(Err(error.to_string()));
                        return;
                    }
                };
                let _ = send.send(Ok(()));
                let mut active = Shortcut::default();
                let mut registered = None;
                let mut message = MSG::default();
                while GetMessageW(&mut message, None, 0, 0).0 > 0 {
                    if message.message == REBIND_MESSAGE {
                        while let Ok(request) = rebind_receive.try_recv() {
                            let result = if request.shortcut == active {
                                Ok(())
                            } else if request.shortcut.is_default() {
                                if let Some(id) = registered.take() {
                                    let _ = UnregisterHotKey(None, id);
                                }
                                DEFAULT_ENABLED.store(true, Ordering::SeqCst);
                                active = request.shortcut;
                                Ok(())
                            } else {
                                let id = if registered == Some(1) { 2 } else { 1 };
                                let mut modifiers = MOD_NOREPEAT;
                                if request.shortcut.ctrl {
                                    modifiers |= MOD_CONTROL;
                                }
                                if request.shortcut.alt {
                                    modifiers |= MOD_ALT;
                                }
                                if request.shortcut.shift {
                                    modifiers |= MOD_SHIFT;
                                }
                                match RegisterHotKey(None, id, modifiers, request.shortcut.key) {
                                    Ok(()) => {
                                        if let Some(previous) = registered.replace(id) { let _ = UnregisterHotKey(None, previous); }
                                        DEFAULT_ENABLED.store(false, Ordering::SeqCst);
                                        active = request.shortcut;
                                        Ok(())
                                    }
                                    Err(_) => Err("Это сочетание уже занято Windows или другим приложением. Выбери другое.".into()),
                                }
                            };
                            DOUBLE_TAP.with(|tap| tap.borrow_mut().cancel());
                            DOWN.store(false, Ordering::Relaxed);
                            let _ = request.reply.send(result);
                        }
                        continue;
                    }
                    if message.message == WM_HOTKEY {
                        if registered == Some(message.wParam.0 as i32)
                            && !CAPTURING.load(Ordering::Relaxed)
                        {
                            toggle();
                        }
                        continue;
                    }
                    let _ = DispatchMessageW(&message);
                }
                if let Some(id) = registered {
                    let _ = UnregisterHotKey(None, id);
                }
                let _ = UnhookWindowsHookEx(hook);
                let _ = UnhookWindowsHookEx(mouse);
            }
            Err(error) => {
                let _ = send.send(Err(error.to_string()));
            }
        }
    });
    receive.recv().map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    fn target() -> InputTarget {
        InputTarget {
            window: 1,
            focus: 2,
            thread: 3,
            layout: 4,
        }
    }

    #[test]
    fn pairs_are_consecutive_short_and_do_not_eat_the_third_press() {
        let mut tap = DoubleTap::default();
        assert!(!tap.press(100, Some(target())));
        assert!(tap.press(300, Some(target())));
        assert!(!tap.press(450, Some(target())));
        assert!(!tap.press(2000, Some(target())));
        assert!(tap.press(3500, Some(target())));
        assert!(!tap.press(3600, Some(target())));
        assert!(!tap.press(5101, Some(target())));
    }

    #[test]
    fn typing_clicks_repeats_unknown_targets_and_focus_changes_cancel_cleanup() {
        let mut tap = DoubleTap::default();
        assert!(!tap.press(100, Some(target())));
        tap.cancel();
        assert!(!tap.press(200, Some(target())));
        assert!(!tap.press(250, None));
        assert!(!tap.press(300, Some(target())));
        for next in [
            InputTarget {
                window: 9,
                ..target()
            },
            InputTarget {
                focus: 9,
                ..target()
            },
            InputTarget {
                layout: 9,
                ..target()
            },
        ] {
            tap.cancel();
            assert!(!tap.press(400, Some(target())));
            assert!(!tap.press(500, Some(next)));
        }
    }

    #[test]
    fn windows_event_clock_wraparound_is_supported() {
        let mut tap = DoubleTap::default();
        assert!(!tap.press(u32::MAX - 100, Some(target())));
        assert!(tap.press(100, Some(target())));
    }
}

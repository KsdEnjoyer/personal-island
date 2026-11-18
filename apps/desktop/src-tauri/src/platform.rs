use std::sync::Mutex;
use windows::Win32::{
    Foundation::HWND,
    System::Threading::GetCurrentProcessId,
    UI::{
        Input::KeyboardAndMouse::{
            GetAsyncKeyState, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
            KEYEVENTF_KEYUP, VK_CONTROL, VK_LWIN, VK_MENU, VK_RWIN, VK_SHIFT, VK_V,
        },
        WindowsAndMessaging::{
            GetForegroundWindow, GetWindowThreadProcessId, IsWindow, SetForegroundWindow,
        },
    },
};

#[derive(Clone, Copy)]
struct Target {
    hwnd: isize,
    pid: u32,
}
#[derive(Default)]
struct Targets {
    previous: Option<Target>,
    pending: Option<Target>,
}
#[derive(Default)]
pub struct PasteTarget(Mutex<Targets>);

impl PasteTarget {
    pub fn remember_foreground(&self) {
        unsafe {
            let hwnd = GetForegroundWindow();
            if hwnd.0.is_null() {
                return;
            }
            let mut pid = 0;
            GetWindowThreadProcessId(hwnd, Some(&mut pid));
            if pid != 0 && pid != GetCurrentProcessId() {
                if let Ok(mut target) = self.0.lock() {
                    target.previous = Some(Target {
                        hwnd: hwnd.0 as isize,
                        pid,
                    });
                }
            }
        }
    }

    pub fn prepare(&self) -> Result<(), String> {
        let mut targets = self
            .0
            .lock()
            .map_err(|_| "Не удалось получить окно вставки")?;
        targets.pending = targets.previous;
        if targets.pending.is_none() {
            return Err("Запись скопирована. Сначала выбери окно для вставки.".into());
        }
        Ok(())
    }

    pub fn paste(&self) -> Result<(), String> {
        let target = self
            .0
            .lock()
            .map_err(|_| "Не удалось получить окно вставки")?
            .pending
            .take()
            .ok_or("Запись скопирована. Сначала выбери окно для вставки.")?;
        let hwnd = HWND(target.hwnd as *mut _);
        unsafe {
            let mut pid = 0;
            GetWindowThreadProcessId(hwnd, Some(&mut pid));
            if !IsWindow(Some(hwnd)).as_bool() || pid != target.pid || pid == GetCurrentProcessId()
            {
                return Err("Запись скопирована, но предыдущее окно уже закрыто.".into());
            }
            let _ = SetForegroundWindow(hwnd);
            for _ in 0..20 {
                if GetForegroundWindow() == hwnd {
                    break;
                }
                std::thread::sleep(std::time::Duration::from_millis(25));
            }
            if GetForegroundWindow() != hwnd {
                return Err("Запись скопирована. Windows не разрешила вернуть фокус — вставь её через Ctrl+V.".into());
            }
            for _ in 0..20 {
                if [VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN]
                    .iter()
                    .all(|key| GetAsyncKeyState(key.0 as i32) >= 0)
                {
                    break;
                }
                std::thread::sleep(std::time::Duration::from_millis(25));
            }
            if [VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN]
                .iter()
                .any(|key| GetAsyncKeyState(key.0 as i32) < 0)
            {
                return Err(
                    "Запись скопирована. Отпусти клавиши-модификаторы и нажми Ctrl+V.".into(),
                );
            }
            if GetForegroundWindow() != hwnd {
                return Err(
                    "Окно сменилось. Запись скопирована — нажми Ctrl+V в нужном окне.".into(),
                );
            }
            let key = |vk, flags| INPUT {
                r#type: INPUT_KEYBOARD,
                Anonymous: INPUT_0 {
                    ki: KEYBDINPUT {
                        wVk: vk,
                        dwFlags: flags,
                        ..Default::default()
                    },
                },
            };
            let inputs = [
                key(VK_CONTROL, Default::default()),
                key(VK_V, Default::default()),
                key(VK_V, KEYEVENTF_KEYUP),
                key(VK_CONTROL, KEYEVENTF_KEYUP),
            ];
            if SendInput(&inputs, std::mem::size_of::<INPUT>() as i32) != inputs.len() as u32 {
                return Err("Запись скопирована. Windows ограничила вставку в это окно — нажми Ctrl+V вручную.".into());
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn paste_target_is_frozen_before_the_island_hides() {
        let target = PasteTarget::default();
        target.0.lock().unwrap().previous = Some(Target { hwnd: 1, pid: 7 });
        target.prepare().unwrap();
        target.0.lock().unwrap().previous = Some(Target { hwnd: 2, pid: 8 });
        assert_eq!(target.0.lock().unwrap().pending.unwrap().hwnd, 1);
    }
    #[test]
    fn missing_or_closed_target_never_receives_input() {
        let target = PasteTarget::default();
        assert!(target.prepare().is_err());
        assert!(target.paste().is_err());
        target.0.lock().unwrap().pending = Some(Target { hwnd: 0, pid: 123 });
        assert!(target.paste().unwrap_err().contains("закрыто"));
    }
}

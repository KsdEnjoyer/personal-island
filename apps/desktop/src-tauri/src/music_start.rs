//! First Play before Yandex publishes a Windows media session.
//! Invoke the installed app's accessible transport button, without moving focus.
use std::path::Path;
use windows::{
    core::{BOOL, PWSTR},
    Win32::{
        Foundation::{CloseHandle, HWND, LPARAM},
        System::{
            Com::{CoCreateInstance, CLSCTX_INPROC_SERVER},
            Threading::{
                OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32,
                PROCESS_QUERY_LIMITED_INFORMATION,
            },
            Variant::VARIANT,
        },
        UI::{
            Accessibility::*,
            WindowsAndMessaging::{EnumWindows, GetClassNameW, GetWindowThreadProcessId},
        },
    },
};

struct Search<'a> {
    executable: &'a Path,
    window: Option<HWND>,
}
fn same_executable(actual: &str, expected: &Path) -> bool {
    actual.replace('/', "\\").to_lowercase()
        == expected.to_string_lossy().replace('/', "\\").to_lowercase()
}
unsafe extern "system" fn find_window(window: HWND, data: LPARAM) -> BOOL {
    let search = &mut *(data.0 as *mut Search<'_>);
    let mut class = [0u16; 64];
    let length = GetClassNameW(window, &mut class);
    if String::from_utf16_lossy(&class[..length.max(0) as usize]) != "Chrome_WidgetWin_1" {
        return BOOL(1);
    }
    let mut pid = 0;
    GetWindowThreadProcessId(window, Some(&mut pid));
    if let Ok(process) = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) {
        let mut path = [0u16; 32768];
        let mut length = path.len() as u32;
        let matches = QueryFullProcessImageNameW(
            process,
            PROCESS_NAME_WIN32,
            PWSTR(path.as_mut_ptr()),
            &mut length,
        )
        .is_ok()
            && same_executable(
                &String::from_utf16_lossy(&path[..length as usize]),
                search.executable,
            );
        let _ = CloseHandle(process);
        if matches {
            search.window = Some(window);
            return BOOL(0);
        }
    }
    BOOL(1)
}

fn is_play(name: &str) -> bool {
    matches!(
        name.to_lowercase().as_str(),
        "воспроизведение" | "воспроизвести" | "play" | "resume"
    )
}
fn is_transport(names: &[String]) -> bool {
    let previous = names.iter().any(|n| {
        matches!(
            n.to_lowercase().as_str(),
            "предыдущая песня" | "предыдущий трек" | "previous track" | "previous song"
        )
    });
    let next = names.iter().any(|n| {
        matches!(
            n.to_lowercase().as_str(),
            "следующая песня" | "следующий трек" | "next track" | "next song"
        )
    });
    previous && next && names.iter().filter(|n| is_play(n)).count() == 1
}

pub fn initial_play(executable: &Path) -> bool {
    // Caller initializes COM on its worker thread. Search only the exact executable.
    unsafe { try_initial_play(executable).unwrap_or(false) }
}
unsafe fn try_initial_play(executable: &Path) -> windows::core::Result<bool> {
    let mut search = Search {
        executable,
        window: None,
    };
    let _ = EnumWindows(Some(find_window), LPARAM(&mut search as *mut _ as isize));
    let Some(window) = search.window else {
        return Ok(false);
    };
    let automation: IUIAutomation = CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER)?;
    let root = automation.ElementFromHandle(window)?;
    let condition = automation.CreatePropertyCondition(
        UIA_ControlTypePropertyId,
        &VARIANT::from(UIA_ButtonControlTypeId.0),
    )?;
    let buttons = root.FindAll(TreeScope_Descendants, &condition)?;
    let walker = automation.ControlViewWalker()?;
    for index in (0..buttons.Length()?.min(256)).rev() {
        let button = buttons.GetElement(index)?;
        if !button.CurrentIsEnabled()?.as_bool() || !is_play(&button.CurrentName()?.to_string()) {
            continue;
        }
        let parent = walker.GetParentElement(&button)?;
        let siblings = parent.FindAll(TreeScope_Children, &condition)?;
        let mut names = Vec::new();
        for sibling in 0..siblings.Length()?.min(64) {
            names.push(siblings.GetElement(sibling)?.CurrentName()?.to_string());
        }
        // Distinguish the player from Play buttons on recommended playlists.
        if is_transport(&names) && is_play(&button.CurrentName()?.to_string()) {
            let invoke: IUIAutomationInvokePattern =
                button.GetCurrentPatternAs(UIA_InvokePatternId)?;
            invoke.Invoke()?;
            return Ok(true);
        }
    }
    Ok(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn scopes_windows_paths_with_both_separators_to_the_exact_installed_executable() {
        let expected = Path::new("C:/Apps/YandexMusic/Яндекс Музыка.exe");
        assert!(same_executable(
            "c:\\apps\\YandexMusic\\Яндекс Музыка.exe",
            expected
        ));
        assert!(!same_executable("C:\\Other\\Яндекс Музыка.exe", expected));
        assert!(!same_executable(
            "C:\\Apps\\YandexMusic\\Other.exe",
            expected
        ));
    }
    #[test]
    fn first_play_requires_a_unique_transport_instead_of_a_recommendation_or_pause() {
        let names = |items: &[&str]| items.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        assert!(is_transport(&names(&[
            "Предыдущая песня",
            "Воспроизведение",
            "Следующая песня"
        ])));
        assert!(is_transport(&names(&[
            "Previous track",
            "Play",
            "Next track"
        ])));
        assert!(!is_transport(&names(&["Воспроизведение", "Моя волна"])));
        assert!(!is_transport(&names(&[
            "Предыдущая песня",
            "Пауза",
            "Следующая песня"
        ])));
        assert!(!is_transport(&names(&[
            "Previous track",
            "Play",
            "Play",
            "Next track"
        ])));
    }
}

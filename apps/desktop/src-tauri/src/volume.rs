//! Per-player Core Audio session gain. Never activates IAudioEndpointVolume.
use serde::Serialize;
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::{Mutex, OnceLock},
    time::{Duration, Instant},
};
use windows::{
    core::{Interface, HSTRING, PWSTR},
    Win32::{
        Foundation::{CloseHandle, PROPERTYKEY},
        Media::Audio::*,
        Storage::Packaging::Appx::GetApplicationUserModelId,
        System::{Com::*, Threading::*},
        UI::Shell::{
            FOLDERID_CommonPrograms, FOLDERID_Programs, IShellLinkW,
            PropertiesSystem::IPropertyStore, SHGetKnownFolderPath, ShellLink, KF_FLAG_DEFAULT,
            SLGP_RAWPATH,
        },
    },
};
#[derive(Serialize)]
pub struct PlayerVolume {
    available: bool,
    level: f32,
    muted: bool,
    scope: &'static str,
}
// Unpackaged players (including Yandex) publish a shortcut AppUserModelID,
// which GetApplicationUserModelId on their audio process cannot resolve.
const APP_ID: PROPERTYKEY = PROPERTYKEY {
    fmtid: windows::core::GUID::from_u128(0x9f4c2855_9f79_4b39_a8d0_e1d42de1d5f3),
    pid: 5,
};
unsafe fn shortcut_target(path: &Path, source: &str) -> Option<String> {
    let link: IShellLinkW = CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER).ok()?;
    link.cast::<IPersistFile>()
        .ok()?
        .Load(&HSTRING::from(path.to_string_lossy().as_ref()), STGM_READ)
        .ok()?;
    let properties: IPropertyStore = link.cast().ok()?;
    if !properties
        .GetValue(&APP_ID)
        .ok()?
        .to_string()
        .eq_ignore_ascii_case(source)
    {
        return None;
    }
    let mut buffer = [0u16; 32768];
    link.GetPath(&mut buffer, std::ptr::null_mut(), SLGP_RAWPATH.0 as u32)
        .ok()?;
    let end = buffer.iter().position(|c| *c == 0)?;
    (end > 0).then(|| String::from_utf16_lossy(&buffer[..end]))
}
unsafe fn find_shortcut(
    root: &Path,
    source: &str,
    depth: u8,
    remaining: &mut usize,
) -> Option<String> {
    if depth == 0 {
        return None;
    }
    for item in std::fs::read_dir(root).ok()?.flatten() {
        if *remaining == 0 {
            break;
        }
        *remaining -= 1;
        let Ok(kind) = item.file_type() else {
            continue;
        };
        if kind.is_symlink() {
            continue;
        }
        let path = item.path();
        if kind.is_dir() {
            if let Some(target) = find_shortcut(&path, source, depth - 1, remaining) {
                return Some(target);
            }
        } else if path
            .extension()
            .is_some_and(|ext| ext.eq_ignore_ascii_case("lnk"))
        {
            if let Some(target) = shortcut_target(&path, source) {
                return Some(target);
            }
        }
    }
    None
}
unsafe fn player_executable(source: &str) -> Option<String> {
    if source.to_ascii_lowercase().ends_with(".exe") {
        return None;
    }
    type Cache = HashMap<String, (Instant, Option<String>)>;
    static CACHE: OnceLock<Mutex<Cache>> = OnceLock::new();
    let mut cache = CACHE
        .get_or_init(Mutex::default)
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    if let Some((time, target)) = cache.get(source) {
        if time.elapsed() < Duration::from_secs(60) {
            return target.clone();
        }
    }
    let mut target = None;
    let mut remaining = 2048;
    for folder in [FOLDERID_Programs, FOLDERID_CommonPrograms] {
        if let Ok(path) = SHGetKnownFolderPath(&folder, KF_FLAG_DEFAULT, None) {
            let root = path.to_string().ok().map(PathBuf::from);
            CoTaskMemFree(Some(path.0.cast()));
            if let Some(root) = root {
                target = find_shortcut(&root, source, 8, &mut remaining);
            }
            if target.is_some() {
                break;
            }
        }
    }
    if cache.len() >= 32 {
        cache.clear();
    }
    cache.insert(source.to_owned(), (Instant::now(), target.clone()));
    target
}
unsafe fn matches_process(pid: u32, source: &str, executable: Option<&str>) -> bool {
    let Ok(process) = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) else {
        return false;
    };
    let mut buffer = [0u16; 32768];
    let mut length = buffer.len() as u32;
    let path = QueryFullProcessImageNameW(
        process,
        PROCESS_NAME_WIN32,
        PWSTR(buffer.as_mut_ptr()),
        &mut length,
    )
    .ok()
    .map(|_| String::from_utf16_lossy(&buffer[..length as usize]));
    let filename = path
        .as_deref()
        .and_then(|path| path.rsplit('\\').next())
        .unwrap_or("");
    let source_file = source.rsplit(['\\', '/']).next().unwrap_or(source);
    let file_match = filename.eq_ignore_ascii_case(source_file);
    let mut length = buffer.len() as u32;
    let app_match =
        GetApplicationUserModelId(process, &mut length, Some(PWSTR(buffer.as_mut_ptr()))).is_ok()
            && String::from_utf16_lossy(&buffer[..length.saturating_sub(1) as usize])
                .eq_ignore_ascii_case(source);
    let _ = CloseHandle(process);
    let shortcut_match = path
        .as_deref()
        .zip(executable)
        .is_some_and(|(path, target)| path.to_lowercase() == target.to_lowercase());
    file_match || app_match || shortcut_match
}
fn access(source: String, level: Option<f32>) -> Result<PlayerVolume, String> {
    if level.is_some_and(|value| !value.is_finite() || !(0.0..=1.0).contains(&value)) {
        return Err("Громкость должна быть от 0 до 100%".into());
    }
    unsafe {
        CoInitializeEx(None, COINIT_MULTITHREADED)
            .ok()
            .map_err(|e| e.to_string())?;
        struct Com;
        impl Drop for Com {
            fn drop(&mut self) {
                unsafe {
                    CoUninitialize();
                }
            }
        }
        let _com = Com;
        let executable = player_executable(&source);
        let devices: IMMDeviceEnumerator =
            CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL).map_err(|e| e.to_string())?;
        let endpoints = devices
            .EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE)
            .map_err(|e| e.to_string())?;
        let mut volumes = Vec::new();
        for index in 0..endpoints.GetCount().unwrap_or(0) {
            let Ok(endpoint) = endpoints.Item(index) else {
                continue;
            };
            let Ok(manager) = endpoint.Activate::<IAudioSessionManager2>(CLSCTX_ALL, None) else {
                continue;
            };
            let Ok(sessions) = manager.GetSessionEnumerator() else {
                continue;
            };
            for index in 0..sessions.GetCount().unwrap_or(0) {
                let Ok(session) = sessions.GetSession(index) else {
                    continue;
                };
                let Ok(control) = session.cast::<IAudioSessionControl2>() else {
                    continue;
                };
                if control.GetState().ok() == Some(AudioSessionStateExpired) {
                    continue;
                }
                if control.GetProcessId().ok().is_some_and(|pid| {
                    pid != 0 && matches_process(pid, &source, executable.as_deref())
                }) {
                    if let Ok(volume) = session.cast::<ISimpleAudioVolume>() {
                        volumes.push(volume);
                    }
                }
            }
        }
        if volumes.is_empty() && level.is_some() {
            return Err("Аудиосессия этого плеера недоступна. Включи воспроизведение.".into());
        }
        if let Some(level) = level {
            for volume in &volumes {
                volume
                    .SetMasterVolume(level, std::ptr::null())
                    .map_err(|e| e.to_string())?;
                // A muted mixer session otherwise stays silent while its slider moves.
                if level > 0.0 {
                    volume
                        .SetMute(false, std::ptr::null())
                        .map_err(|e| e.to_string())?;
                }
            }
        }
        Ok(PlayerVolume {
            available: !volumes.is_empty(),
            level: volumes
                .first()
                .and_then(|v| v.GetMasterVolume().ok())
                .unwrap_or(0.0),
            muted: volumes
                .first()
                .and_then(|v| v.GetMute().ok())
                .is_some_and(|v| v.as_bool()),
            scope: "player",
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use windows::Win32::System::Com::StructuredStorage::PROPVARIANT;
    #[test]
    fn unpackaged_shortcut_id_resolves_only_its_exact_executable() {
        unsafe {
            CoInitializeEx(None, COINIT_MULTITHREADED).ok().unwrap();
            let folder = tempfile::tempdir().unwrap();
            let path = folder.path().join("Player.lnk");
            let executable = std::env::current_exe().unwrap();
            let link: IShellLinkW =
                CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER).unwrap();
            link.SetPath(&HSTRING::from(executable.to_string_lossy().as_ref()))
                .unwrap();
            let properties: IPropertyStore = link.cast().unwrap();
            properties
                .SetValue(&APP_ID, &PROPVARIANT::from("QA.Unpackaged.Player"))
                .unwrap();
            properties.Commit().unwrap();
            link.cast::<IPersistFile>()
                .unwrap()
                .Save(&HSTRING::from(path.to_string_lossy().as_ref()), true)
                .unwrap();
            assert_eq!(
                shortcut_target(&path, "QA.Unpackaged.Player"),
                Some(executable.to_string_lossy().into_owned())
            );
            assert_eq!(shortcut_target(&path, "QA.Other.Player"), None);
            assert_eq!(
                find_shortcut(folder.path(), "QA.Unpackaged.Player", 8, &mut 100),
                Some(executable.to_string_lossy().into_owned())
            );
            assert!(matches_process(
                GetCurrentProcessId(),
                "QA.Unpackaged.Player",
                Some(executable.to_string_lossy().as_ref())
            ));
            assert!(!matches_process(
                GetCurrentProcessId(),
                "QA.Other.Player",
                Some("C:\\Other\\player.exe")
            ));
            drop(properties);
            drop(link);
            CoUninitialize();
        }
    }
}
#[tauri::command]
pub async fn player_volume(session_id: String, level: Option<f32>) -> Result<PlayerVolume, String> {
    tauri::async_runtime::spawn_blocking(move || access(session_id, level))
        .await
        .map_err(|e| e.to_string())?
}

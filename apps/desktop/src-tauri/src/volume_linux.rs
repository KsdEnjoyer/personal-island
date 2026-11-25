//! MPRIS volume with a PulseAudio/PipeWire stream fallback. Never changes sink volume.
use serde::Serialize;
use std::process::Command;

#[derive(Serialize)]
pub struct PlayerVolume {
    available: bool,
    level: f32,
    muted: bool,
    scope: &'static str,
}

fn access(session_id: &str, level: Option<f32>) -> Result<PlayerVolume, String> {
    if level.is_some_and(|value| !value.is_finite() || !(0.0..=1.0).contains(&value)) {
        return Err("Громкость должна быть от 0 до 100%".into());
    }
    if let Ok(volume) = mpris_volume(session_id, level) {
        return Ok(volume);
    }
    pulse_volume(session_id, level)
}

fn mpris_volume(session_id: &str, level: Option<f32>) -> Result<PlayerVolume, String> {
    let mut command = Command::new("playerctl");
    command.args(["-p", session_id, "volume"]);
    if let Some(level) = level {
        command.arg(format!("{level:.3}"));
    }
    let output = command
        .output()
        .map_err(|e| format!("Не удалось запустить playerctl: {e}"))?;
    if !output.status.success() {
        return Err("Плеер не поддерживает регулировку громкости через MPRIS".into());
    }
    let current = if level.is_some() {
        Command::new("playerctl")
            .args(["-p", session_id, "volume"])
            .output()
            .map_err(|e| e.to_string())?
    } else {
        output
    };
    if !current.status.success() {
        return Err("Не удалось прочитать громкость плеера".into());
    }
    let value = String::from_utf8_lossy(&current.stdout)
        .trim()
        .parse::<f32>()
        .map_err(|e| e.to_string())?;
    Ok(PlayerVolume {
        available: true,
        level: value.clamp(0.0, 1.0),
        muted: value == 0.0,
        scope: "player",
    })
}

pub(crate) fn mpris_owner_pid(session_id: &str) -> Option<u32> {
    let output = Command::new("gdbus")
        .args([
            "call",
            "--session",
            "--dest",
            "org.freedesktop.DBus",
            "--object-path",
            "/org/freedesktop/DBus",
            "--method",
            "org.freedesktop.DBus.GetConnectionUnixProcessID",
            &format!("org.mpris.MediaPlayer2.{session_id}"),
        ])
        .output()
        .ok()?;
    output.status.success().then_some(())?;
    String::from_utf8_lossy(&output.stdout)
        .split("uint32 ")
        .nth(1)?
        .chars()
        .take_while(char::is_ascii_digit)
        .collect::<String>()
        .parse()
        .ok()
}

#[derive(Debug, PartialEq)]
struct SinkInput {
    index: u32,
    level: f32,
    muted: bool,
}

fn normalized(value: &str) -> String {
    value
        .chars()
        .filter(|character| character.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

fn binary_matches(session_id: &str, binary: &str) -> bool {
    let player = normalized(session_id.split('.').next().unwrap_or(session_id));
    let binary = normalized(binary);
    player.len() >= 4
        && binary.len() >= 4
        && (player == binary || player.ends_with(&binary) || binary.ends_with(&player))
}

fn sink_input(entry: &serde_json::Value) -> Option<SinkInput> {
    let channel = entry.get("volume")?.as_object()?.values().next()?;
    let value = channel.get("value")?.as_u64()? as f32 / 65536.0;
    Some(SinkInput {
        index: entry.get("index")?.as_u64()?.try_into().ok()?,
        level: value.clamp(0.0, 1.0),
        muted: entry.get("mute")?.as_bool()?,
    })
}

fn matching_sink_inputs(data: &[u8], session_id: &str, owner_pid: Option<u32>) -> Vec<SinkInput> {
    let Ok(entries) = serde_json::from_slice::<Vec<serde_json::Value>>(data) else {
        return Vec::new();
    };
    let mut by_pid = Vec::new();
    let mut by_binary = Vec::new();
    for entry in entries {
        let Some(input) = sink_input(&entry) else {
            continue;
        };
        let properties = &entry["properties"];
        if owner_pid.is_some_and(|pid| {
            properties["application.process.id"]
                .as_str()
                .and_then(|value| value.parse::<u32>().ok())
                == Some(pid)
        }) {
            by_pid.push(input);
        } else if properties["application.process.binary"]
            .as_str()
            .is_some_and(|binary| binary_matches(session_id, binary))
        {
            by_binary.push(input);
        }
    }
    if by_pid.is_empty() {
        by_binary
    } else {
        by_pid
    }
}

fn pulse_volume(session_id: &str, level: Option<f32>) -> Result<PlayerVolume, String> {
    let output = Command::new("pactl")
        .args(["-f", "json", "list", "sink-inputs"])
        .output()
        .map_err(|e| format!("Не удалось запустить pactl: {e}"))?;
    if !output.status.success() {
        return Err("Не удалось прочитать звуковые потоки PulseAudio/PipeWire".into());
    }
    let inputs = matching_sink_inputs(&output.stdout, session_id, mpris_owner_pid(session_id));
    if inputs.is_empty() && level.is_some() {
        return Err("Аудиопоток этого плеера недоступен. Включи воспроизведение.".into());
    }
    if let Some(level) = level {
        for input in &inputs {
            let index = input.index.to_string();
            let percent = format!("{}%", (level * 100.0).round() as u32);
            let status = Command::new("pactl")
                .args(["set-sink-input-volume", &index, &percent])
                .status()
                .map_err(|e| e.to_string())?;
            if !status.success() {
                return Err("Не удалось изменить громкость плеера".into());
            }
            if level > 0.0 {
                let status = Command::new("pactl")
                    .args(["set-sink-input-mute", &index, "0"])
                    .status()
                    .map_err(|e| e.to_string())?;
                if !status.success() {
                    return Err("Не удалось включить звук плеера".into());
                }
            }
        }
    }
    Ok(PlayerVolume {
        available: !inputs.is_empty(),
        level: level.unwrap_or_else(|| inputs.first().map_or(0.0, |input| input.level)),
        muted: level.map_or_else(
            || inputs.first().is_some_and(|input| input.muted),
            |value| value == 0.0,
        ),
        scope: "player",
    })
}

#[tauri::command]
pub async fn player_volume(session_id: String, level: Option<f32>) -> Result<PlayerVolume, String> {
    tauri::async_runtime::spawn_blocking(move || access(&session_id, level))
        .await
        .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pulse_fallback_only_selects_the_player_stream() {
        let data = br#"[
          {"index":1,"mute":false,"volume":{"left":{"value":32768}},"properties":{"application.process.id":"42","application.process.binary":"yandex-music"}},
          {"index":2,"mute":false,"volume":{"left":{"value":65536}},"properties":{"application.process.id":"99","application.process.binary":"firefox"}}
        ]"#;
        assert_eq!(
            matching_sink_inputs(data, "YandexMusic.instance1", Some(42)),
            vec![SinkInput {
                index: 1,
                level: 0.5,
                muted: false
            }]
        );
        assert_eq!(
            matching_sink_inputs(data, "firefox.instance1", Some(100)),
            vec![SinkInput {
                index: 2,
                level: 1.0,
                muted: false
            }]
        );
    }
}

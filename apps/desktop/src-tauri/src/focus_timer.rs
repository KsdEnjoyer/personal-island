use std::sync::atomic::{AtomicU64, Ordering};
use tauri::{Emitter, Manager};

#[derive(Default)]
pub struct FocusTimer(AtomicU64);

impl FocusTimer {
    fn set_deadline(&self, deadline: Option<u64>) {
        self.0.store(deadline.unwrap_or(0), Ordering::SeqCst);
    }

    fn take_due(&self, now: u64) -> Option<u64> {
        let deadline = self.0.load(Ordering::SeqCst);
        if deadline == 0 || deadline > now {
            return None;
        }
        self.0
            .compare_exchange(deadline, 0, Ordering::SeqCst, Ordering::SeqCst)
            .ok()
    }
}

#[tauri::command]
pub fn set_focus_timer_deadline(timer: tauri::State<'_, FocusTimer>, deadline: Option<u64>) {
    timer.set_deadline(deadline);
}

pub fn check(app: &tauri::AppHandle, window: &tauri::WebviewWindow) {
    let now = chrono::Utc::now().timestamp_millis().max(0) as u64;
    let Some(deadline) = app.state::<FocusTimer>().take_due(now) else {
        return;
    };
    tauri::async_runtime::spawn_blocking(|| {
        if !play_chime() {
            eprintln!("Could not play the focus timer chime");
        }
    });
    if let Err(error) = super::reveal_compact(app, "focus") {
        eprintln!("Could not reveal the focus timer: {error}");
    }
    if let Err(error) = window.emit("focus-timer-finished", deadline) {
        eprintln!("Could not deliver the focus timer alert: {error}");
    }
}

const SAMPLE_RATE: u32 = 24_000;

fn chime() -> Vec<u8> {
    let notes = [(659.25, 160), (783.99, 160), (1046.50, 320)];
    let data_size = notes.iter().map(|(_, ms)| ms + 35).sum::<u32>() * SAMPLE_RATE / 1000 * 2;
    let mut wav = Vec::with_capacity(44 + data_size as usize);
    wav.extend(b"RIFF");
    wav.extend((36 + data_size).to_le_bytes());
    wav.extend(b"WAVEfmt \x10\0\0\0\x01\0\x01\0");
    wav.extend(SAMPLE_RATE.to_le_bytes());
    wav.extend((SAMPLE_RATE * 2).to_le_bytes());
    wav.extend(b"\x02\0\x10\0data");
    wav.extend(data_size.to_le_bytes());

    for (frequency, ms) in notes {
        let samples = ms * SAMPLE_RATE / 1000;
        for index in 0..samples {
            let time = f64::from(index) / f64::from(SAMPLE_RATE);
            let attack = (time / 0.012).min(1.0);
            let release = f64::from(samples - index) / f64::from(samples);
            let tone = (std::f64::consts::TAU * frequency * time).sin();
            let sample = (tone * attack * release * 11_000.0) as i16;
            wav.extend(sample.to_le_bytes());
        }
        wav.resize(wav.len() + (35 * SAMPLE_RATE / 1000 * 2) as usize, 0);
    }
    wav
}

#[cfg(windows)]
fn play_chime() -> bool {
    use windows::{
        core::PCWSTR,
        Win32::Media::Audio::{PlaySoundW, SND_MEMORY, SND_NODEFAULT, SND_SYNC},
    };

    let wav = chime();
    // Synchronous memory playback keeps the WAV buffer alive until the last note.
    unsafe {
        PlaySoundW(
            PCWSTR(wav.as_ptr().cast()),
            None,
            SND_MEMORY | SND_NODEFAULT | SND_SYNC,
        )
    }
    .as_bool()
}

#[cfg(target_os = "linux")]
fn play_chime() -> bool {
    use std::{
        io::Write,
        process::{Command, Stdio},
    };

    let wav = chime();
    let rate = SAMPLE_RATE.to_string();
    let players: [(&str, &[&str], &[u8]); 3] = [
        (
            "pacat",
            &[
                "--playback",
                "--raw",
                "--format=s16le",
                "--rate",
                &rate,
                "--channels=1",
                "--latency-msec=100",
            ],
            &wav[44..],
        ),
        (
            "pw-play",
            &[
                "--raw",
                "--format=s16",
                "--rate",
                &rate,
                "--channels=1",
                "-",
            ],
            &wav[44..],
        ),
        ("aplay", &["-q", "-t", "wav"], &wav),
    ];
    for (player, args, data) in players {
        let Ok(mut child) = Command::new(player)
            .args(args)
            .stdin(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
        else {
            continue;
        };
        let written = child
            .stdin
            .take()
            .is_some_and(|mut input| input.write_all(data).is_ok());
        if child.wait().is_ok_and(|status| status.success()) && written {
            return true;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_current_deadline_can_ring_once() {
        let timer = FocusTimer::default();
        timer.set_deadline(Some(1_000));
        assert_eq!(timer.take_due(999), None);
        timer.set_deadline(None);
        assert_eq!(timer.take_due(1_000), None);
        timer.set_deadline(Some(2_000));
        timer.set_deadline(Some(3_000));
        assert_eq!(timer.take_due(2_000), None);
        assert_eq!(timer.take_due(3_000), Some(3_000));
        assert_eq!(timer.take_due(3_001), None);
    }
}

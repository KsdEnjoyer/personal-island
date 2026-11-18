//! Capture the current PulseAudio/PipeWire output monitor. PCM stays in memory.
use serde::Serialize;
use std::{
    io::Read,
    os::fd::AsRawFd,
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, RwLock,
    },
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager};

const BANDS: usize = 10;
const CENTERS: [f32; BANDS] = [45., 75., 120., 200., 350., 650., 1200., 2400., 4800., 9000.];

#[derive(Clone, Default, Serialize)]
pub struct AudioFrame {
    bands: [f32; BANDS],
    bass: f32,
    level: f32,
    impact: f32,
    available: bool,
}

#[derive(Default)]
pub struct AudioReactivity {
    enabled: AtomicBool,
    streaming: AtomicBool,
    latest: RwLock<AudioFrame>,
    error: RwLock<Option<String>>,
}

#[derive(Serialize)]
pub struct AudioStatus {
    enabled: bool,
    streaming: bool,
    frame: AudioFrame,
    error: Option<String>,
}

#[tauri::command]
pub fn set_audio_reactivity(state: tauri::State<'_, Arc<AudioReactivity>>, enabled: bool) {
    state.enabled.store(enabled, Ordering::Relaxed);
}

#[tauri::command]
pub fn get_audio_reactivity(state: tauri::State<'_, Arc<AudioReactivity>>) -> AudioStatus {
    AudioStatus {
        enabled: state.enabled.load(Ordering::Relaxed),
        streaming: state.streaming.load(Ordering::Relaxed),
        frame: state
            .latest
            .read()
            .map(|frame| frame.clone())
            .unwrap_or_default(),
        error: state.error.read().ok().and_then(|error| error.clone()),
    }
}

#[derive(Clone, Copy, Default)]
struct Bandpass {
    b0: f32,
    a1: f32,
    a2: f32,
    x1: f32,
    x2: f32,
    y1: f32,
    y2: f32,
}
impl Bandpass {
    fn new(rate: f32, frequency: f32) -> Self {
        let omega = 2.0 * std::f32::consts::PI * frequency.min(rate * 0.44) / rate;
        let alpha = omega.sin() / (2.0 * 0.9);
        let norm = 1.0 + alpha;
        Self {
            b0: alpha / norm,
            a1: -2.0 * omega.cos() / norm,
            a2: (1.0 - alpha) / norm,
            ..Self::default()
        }
    }
    fn sample(&mut self, x: f32) -> f32 {
        let y = self.b0 * (x - self.x2) - self.a1 * self.y1 - self.a2 * self.y2;
        self.x2 = self.x1;
        self.x1 = x;
        self.y2 = self.y1;
        self.y1 = y;
        y
    }
}
struct Analyzer {
    filters: Vec<[Bandpass; BANDS]>,
    sums: [f64; BANDS],
    total: f64,
    count: usize,
    frames: usize,
    block: usize,
    reference: f32,
    bass_average: f32,
}
impl Analyzer {
    fn new() -> Self {
        Self {
            filters: (0..2)
                .map(|_| CENTERS.map(|f| Bandpass::new(48000., f)))
                .collect(),
            sums: [0.; BANDS],
            total: 0.,
            count: 0,
            frames: 0,
            block: 1200,
            reference: 0.08,
            bass_average: 0.005,
        }
    }
    fn sample(&mut self, channel: usize, value: f32) {
        let x = if value.is_finite() {
            value.clamp(-1., 1.)
        } else {
            0.
        };
        self.total += (x * x) as f64;
        self.count += 1;
        for (i, filter) in self.filters[channel].iter_mut().enumerate() {
            let y = filter.sample(x);
            self.sums[i] += (y * y) as f64;
        }
    }
    fn end_frame(&mut self) -> Option<AudioFrame> {
        self.frames += 1;
        if self.frames < self.block {
            return None;
        }
        let level = (self.total / self.count.max(1) as f64).sqrt() as f32;
        let raw = self
            .sums
            .map(|sum| (sum / self.count.max(1) as f64).sqrt() as f32);
        self.reference +=
            (level - self.reference) * if level > self.reference { 0.025 } else { 0.008 };
        let reference = self.reference.max(0.015);
        let bass = raw[..3].iter().copied().fold(0., f32::max);
        let impact =
            ((bass - self.bass_average * 1.25) / self.bass_average.max(0.012)).clamp(0., 1.);
        self.bass_average += (bass - self.bass_average) * 0.06;
        let gate = if level < 0.00025 { 0. } else { 1. };
        let frame = AudioFrame {
            available: true,
            level: (level / reference).sqrt().clamp(0., 1.) * gate,
            bass: (bass / (reference * 0.8)).powf(0.75).clamp(0., 1.) * gate,
            impact: impact * gate,
            bands: raw.map(|value| (value / (reference * 0.7)).powf(0.8).clamp(0., 1.) * gate),
        };
        self.sums.fill(0.);
        self.total = 0.;
        self.count = 0;
        self.frames = 0;
        Some(frame)
    }
}

fn default_monitor() -> Result<String, String> {
    let output = Command::new("pactl")
        .arg("get-default-sink")
        .output()
        .map_err(|e| format!("Установи pulseaudio-utils или pipewire-pulse: {e}"))?;
    if !output.status.success() {
        return Err("Нет доступного аудиовыхода".into());
    }
    let sink = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if sink.is_empty() {
        return Err("Нет доступного аудиовыхода".into());
    }
    Ok(format!("{sink}.monitor"))
}

fn open_monitor(monitor: &str) -> Result<Child, String> {
    let mut child = Command::new("parec")
        .args([
            "--device",
            monitor,
            "--format=float32le",
            "--rate=48000",
            "--channels=2",
            "--raw",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("Установи parec (pulseaudio-utils): {e}"))?;
    let fd = child.stdout.as_ref().unwrap().as_raw_fd();
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
    if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
        let _ = child.kill();
        let _ = child.wait();
        return Err("Не удалось настроить чтение аудиовыхода".into());
    }
    Ok(child)
}

fn publish(app: &tauri::AppHandle, state: &AudioReactivity, frame: AudioFrame) {
    if let Ok(mut latest) = state.latest.write() {
        *latest = frame.clone();
    }
    let _ = app.emit("island-audio", frame);
}

fn stop_stream(child: &mut Option<Child>) {
    if let Some(mut old) = child.take() {
        let _ = old.kill();
        let _ = old.wait();
    }
}

pub fn start(app: tauri::AppHandle) {
    let state = app.state::<Arc<AudioReactivity>>().inner().clone();
    std::thread::spawn(move || {
        let mut child: Option<Child> = None;
        let mut source = String::new();
        let mut analyzer = Analyzer::new();
        let mut pending = Vec::new();
        let mut retry = Instant::now();
        let mut checked = Instant::now();
        let mut emitted = Instant::now();
        let mut last_data = Instant::now();
        loop {
            if app.get_webview_window("main").is_none() {
                break;
            }
            let visible = app
                .get_webview_window("main")
                .and_then(|window| window.is_visible().ok())
                .unwrap_or(false);
            if !state.enabled.load(Ordering::Relaxed) || !visible {
                if child.is_some() {
                    stop_stream(&mut child);
                    state.streaming.store(false, Ordering::Relaxed);
                    publish(&app, &state, AudioFrame::default());
                }
                pending.clear();
                retry = Instant::now();
                std::thread::sleep(Duration::from_millis(120));
                continue;
            }
            if child.is_none() && Instant::now() >= retry {
                match default_monitor()
                    .and_then(|monitor| open_monitor(&monitor).map(|child| (monitor, child)))
                {
                    Ok((monitor, stream)) => {
                        source = monitor;
                        child = Some(stream);
                        analyzer = Analyzer::new();
                        pending.clear();
                        last_data = Instant::now();
                        state.streaming.store(true, Ordering::Relaxed);
                        if let Ok(mut error) = state.error.write() {
                            *error = None;
                        }
                    }
                    Err(message) => {
                        if let Ok(mut error) = state.error.write() {
                            *error = Some(message);
                        }
                        state.streaming.store(false, Ordering::Relaxed);
                        retry = Instant::now() + Duration::from_secs(2);
                    }
                }
                checked = Instant::now();
            }
            if checked.elapsed() >= Duration::from_secs(1) {
                if child.is_some() && default_monitor().ok().as_deref() != Some(&source) {
                    stop_stream(&mut child);
                    state.streaming.store(false, Ordering::Relaxed);
                    retry = Instant::now();
                }
                checked = Instant::now();
            }
            if let Some(stream) = child.as_mut() {
                let mut bytes = [0u8; 16384];
                match stream.stdout.as_mut().unwrap().read(&mut bytes) {
                    Ok(0) => {
                        stop_stream(&mut child);
                        state.streaming.store(false, Ordering::Relaxed);
                        retry = Instant::now() + Duration::from_secs(1);
                    }
                    Ok(size) => {
                        last_data = Instant::now();
                        pending.extend_from_slice(&bytes[..size]);
                        let whole = pending.len() / 8 * 8;
                        let mut latest = None;
                        for frame in pending[..whole].chunks_exact(8) {
                            for channel in 0..2 {
                                let offset = channel * 4;
                                analyzer.sample(
                                    channel,
                                    f32::from_le_bytes(
                                        frame[offset..offset + 4].try_into().unwrap(),
                                    ),
                                );
                            }
                            if let Some(next) = analyzer.end_frame() {
                                latest = Some(next);
                            }
                        }
                        pending.drain(..whole);
                        if let Some(frame) = latest {
                            if emitted.elapsed() >= Duration::from_millis(33) {
                                publish(&app, &state, frame);
                                emitted = Instant::now();
                            }
                        }
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {}
                    Err(_) => {
                        stop_stream(&mut child);
                        state.streaming.store(false, Ordering::Relaxed);
                        retry = Instant::now() + Duration::from_secs(1);
                    }
                }
                if last_data.elapsed() > Duration::from_millis(150)
                    && emitted.elapsed() >= Duration::from_millis(100)
                {
                    publish(
                        &app,
                        &state,
                        AudioFrame {
                            available: true,
                            ..Default::default()
                        },
                    );
                    emitted = Instant::now();
                }
            }
            std::thread::sleep(Duration::from_millis(12));
        }
        stop_stream(&mut child);
    });
}

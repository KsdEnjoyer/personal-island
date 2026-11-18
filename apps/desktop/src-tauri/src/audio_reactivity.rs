//! Local render-endpoint analysis. PCM stays in memory and is never emitted.
use serde::Serialize;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, RwLock,
    },
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager};
use windows::{
    core::PWSTR,
    Win32::{Media::Audio::*, System::Com::*},
};

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
        frame: state.latest.read().map(|v| v.clone()).unwrap_or_default(),
        error: state.error.read().ok().and_then(|v| v.clone()),
    }
}

// A constant-Q filter bank retains bass/treble separately and avoids allocating
// FFT buffers on every audio packet. Channels are analysed independently, so
// out-of-phase stereo cannot cancel a kick drum.
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
    fn new(rate: u32, channels: usize) -> Self {
        Self {
            filters: (0..channels)
                .map(|_| CENTERS.map(|f| Bandpass::new(rate as f32, f)))
                .collect(),
            sums: [0.; BANDS],
            total: 0.,
            count: 0,
            frames: 0,
            block: (rate as usize / 40).max(1),
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
        // The slow reference preserves sudden drops; silence never gets auto-
        // amplified into motion. New samples arrive every 25 ms.
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
            bands: raw.map(|v| (v / (reference * 0.7)).powf(0.8).clamp(0., 1.) * gate),
        };
        self.sums.fill(0.);
        self.total = 0.;
        self.count = 0;
        self.frames = 0;
        Some(frame)
    }
}

#[derive(Clone, Copy)]
struct SampleFormat {
    channels: usize,
    rate: u32,
    stride: usize,
    bytes: usize,
    float: bool,
}
impl SampleFormat {
    unsafe fn parse(pointer: *const WAVEFORMATEX) -> Result<Self, String> {
        let f = pointer.read_unaligned();
        let tag = if f.wFormatTag == 0xfffe && f.cbSize >= 22 {
            (pointer as *const WAVEFORMATEXTENSIBLE)
                .read_unaligned()
                .SubFormat
                .data1 as u16
        } else {
            f.wFormatTag
        };
        let result = Self {
            channels: f.nChannels as usize,
            rate: f.nSamplesPerSec,
            stride: f.nBlockAlign as usize,
            bytes: f.wBitsPerSample as usize / 8,
            float: tag == 3,
        };
        if !(1..=8).contains(&result.channels)
            || !(8000..=192000).contains(&result.rate)
            || result.stride < result.channels * result.bytes
            || !matches!(
                (tag, result.bytes),
                (3, 4) | (3, 8) | (1, 1) | (1, 2) | (1, 3) | (1, 4)
            )
        {
            return Err("Unsupported output audio format".into());
        }
        Ok(result)
    }
    fn decode(self, data: &[u8]) -> f32 {
        let value = match (self.float, self.bytes) {
            (true, 4) => f32::from_le_bytes(data[..4].try_into().unwrap()),
            (true, 8) => f64::from_le_bytes(data[..8].try_into().unwrap()) as f32,
            (false, 1) => (data[0] as f32 - 128.) / 128.,
            (false, 2) => i16::from_le_bytes(data[..2].try_into().unwrap()) as f32 / 32768.,
            (false, 3) => {
                ((i32::from_le_bytes([0, data[0], data[1], data[2]]) >> 8) as f32) / 8388608.
            }
            (false, 4) => i32::from_le_bytes(data[..4].try_into().unwrap()) as f32 / 2147483648.,
            _ => 0.,
        };
        if value.is_finite() {
            value.clamp(-1., 1.)
        } else {
            0.
        }
    }
}

struct Loopback {
    client: IAudioClient,
    capture: IAudioCaptureClient,
    format: SampleFormat,
    analyzer: Analyzer,
    id: String,
    last_packet: Instant,
}
impl Drop for Loopback {
    fn drop(&mut self) {
        unsafe {
            let _ = self.client.Stop();
        }
    }
}
unsafe fn endpoint_id(device: &IMMDevice) -> Result<String, String> {
    let id: PWSTR = device.GetId().map_err(|e| e.to_string())?;
    let result = id.to_string().map_err(|e| e.to_string());
    CoTaskMemFree(Some(id.0 as *const _));
    result
}
impl Loopback {
    unsafe fn open(devices: &IMMDeviceEnumerator) -> Result<Self, String> {
        let device = devices
            .GetDefaultAudioEndpoint(eRender, eMultimedia)
            .map_err(|e| e.to_string())?;
        let id = endpoint_id(&device)?;
        let client: IAudioClient = device
            .Activate(CLSCTX_ALL, None)
            .map_err(|e| e.to_string())?;
        let mix = client.GetMixFormat().map_err(|e| e.to_string())?;
        let format = SampleFormat::parse(mix);
        let initialized = if format.is_ok() {
            client
                .Initialize(
                    AUDCLNT_SHAREMODE_SHARED,
                    AUDCLNT_STREAMFLAGS_LOOPBACK,
                    1_000_000,
                    0,
                    mix,
                    None,
                )
                .map_err(|e| e.to_string())
        } else {
            Ok(())
        };
        CoTaskMemFree(Some(mix as *const _));
        let format = format?;
        initialized?;
        let capture: IAudioCaptureClient = client.GetService().map_err(|e| e.to_string())?;
        client.Start().map_err(|e| e.to_string())?;
        Ok(Self {
            client,
            capture,
            format,
            analyzer: Analyzer::new(format.rate, format.channels),
            id,
            last_packet: Instant::now(),
        })
    }
    unsafe fn drain(&mut self) -> Result<Option<AudioFrame>, String> {
        let mut latest: Option<AudioFrame> = None;
        for _ in 0..64 {
            if self
                .capture
                .GetNextPacketSize()
                .map_err(|e| e.to_string())?
                == 0
            {
                break;
            }
            let (mut pointer, mut frames, mut flags) = (std::ptr::null_mut(), 0, 0);
            self.capture
                .GetBuffer(&mut pointer, &mut frames, &mut flags, None, None)
                .map_err(|e| e.to_string())?;
            self.last_packet = Instant::now();
            let silent = flags & AUDCLNT_BUFFERFLAGS_SILENT.0 as u32 != 0 || pointer.is_null();
            if frames <= self.format.rate {
                let bytes = if silent {
                    &[][..]
                } else {
                    std::slice::from_raw_parts(pointer, frames as usize * self.format.stride)
                };
                for frame in 0..frames as usize {
                    for channel in 0..self.format.channels {
                        let offset = frame * self.format.stride + channel * self.format.bytes;
                        let sample = if silent {
                            0.
                        } else {
                            self.format
                                .decode(&bytes[offset..offset + self.format.bytes])
                        };
                        self.analyzer.sample(channel, sample);
                    }
                    if let Some(mut next) = self.analyzer.end_frame() {
                        // Preserve an onset even if several packets are drained together.
                        if let Some(previous) = latest.as_ref() {
                            next.impact = next.impact.max(previous.impact);
                        }
                        latest = Some(next);
                    }
                }
            }
            self.capture
                .ReleaseBuffer(frames)
                .map_err(|e| e.to_string())?;
        }
        if self.last_packet.elapsed() > Duration::from_millis(150) {
            return Ok(Some(AudioFrame {
                available: true,
                ..Default::default()
            }));
        }
        Ok(latest)
    }
}

fn publish(app: &tauri::AppHandle, state: &AudioReactivity, frame: AudioFrame) {
    if let Ok(mut latest) = state.latest.write() {
        *latest = frame.clone();
    }
    let _ = app.emit("island-audio", frame);
}

pub fn start(app: tauri::AppHandle) {
    let state = app.state::<Arc<AudioReactivity>>().inner().clone();
    std::thread::spawn(move || unsafe {
        if CoInitializeEx(None, COINIT_MULTITHREADED).is_err() {
            return;
        }
        let devices: Result<IMMDeviceEnumerator, _> =
            CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL);
        let Ok(devices) = devices else {
            CoUninitialize();
            return;
        };
        let mut stream: Option<Loopback> = None;
        let mut retry = Instant::now();
        let mut checked = Instant::now();
        let mut emitted = Instant::now();
        let mut pending: Option<AudioFrame> = None;
        loop {
            let visible = app
                .get_webview_window("main")
                .and_then(|w| w.is_visible().ok())
                .unwrap_or(false);
            if !state.enabled.load(Ordering::Relaxed) || !visible {
                if stream.take().is_some() {
                    state.streaming.store(false, Ordering::Relaxed);
                    publish(&app, &state, AudioFrame::default());
                }
                pending = None;
                retry = Instant::now();
                std::thread::sleep(Duration::from_millis(120));
                continue;
            }
            if stream.is_none() && Instant::now() >= retry {
                stream = match Loopback::open(&devices) {
                    Ok(stream) => {
                        if let Ok(mut error) = state.error.write() {
                            *error = None;
                        }
                        Some(stream)
                    }
                    Err(message) => {
                        if let Ok(mut error) = state.error.write() {
                            *error = Some(message);
                        }
                        None
                    }
                };
                state.streaming.store(stream.is_some(), Ordering::Relaxed);
                if stream.is_none() {
                    publish(&app, &state, AudioFrame::default());
                    retry = Instant::now() + Duration::from_secs(1);
                }
                checked = Instant::now();
            }
            if checked.elapsed() >= Duration::from_secs(1) {
                let id = devices
                    .GetDefaultAudioEndpoint(eRender, eMultimedia)
                    .ok()
                    .and_then(|d| endpoint_id(&d).ok());
                if stream.as_ref().is_some_and(|s| Some(&s.id) != id.as_ref()) {
                    stream = None;
                    pending = None;
                    state.streaming.store(false, Ordering::Relaxed);
                }
                checked = Instant::now();
            }
            if let Some(active) = stream.as_mut() {
                match active.drain() {
                    Ok(Some(mut frame)) => {
                        if let Some(old) = pending.as_ref() {
                            frame.impact = frame.impact.max(old.impact);
                        }
                        pending = Some(frame);
                    }
                    Ok(None) => {}
                    Err(_) => {
                        stream = None;
                        pending = None;
                        state.streaming.store(false, Ordering::Relaxed);
                        publish(&app, &state, AudioFrame::default());
                        retry = Instant::now() + Duration::from_millis(500);
                    }
                }
            }
            if emitted.elapsed() >= Duration::from_millis(33) {
                if let Some(frame) = pending.take() {
                    publish(&app, &state, frame);
                    emitted = Instant::now();
                }
            }
            std::thread::sleep(if stream.is_some() {
                Duration::from_millis(8)
            } else {
                Duration::from_millis(120)
            });
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    fn tone(
        analyzer: &mut Analyzer,
        frequency: f32,
        amplitude: f32,
        count: usize,
        opposite: bool,
    ) -> AudioFrame {
        let mut result = AudioFrame::default();
        for i in 0..count {
            let x = (i as f32 * frequency * 2. * std::f32::consts::PI / 48000.).sin() * amplitude;
            analyzer.sample(0, x);
            analyzer.sample(1, if opposite { -x } else { x });
            if let Some(frame) = analyzer.end_frame() {
                result = frame;
            }
        }
        result
    }
    #[test]
    fn bass_drop_is_distinct_from_treble_and_silence() {
        let mut analyzer = Analyzer::new(48000, 2);
        let silence = tone(&mut analyzer, 75., 0., 48000, false);
        assert_eq!(silence.bass, 0.);
        assert_eq!(silence.impact, 0.);
        let quiet = tone(&mut analyzer, 75., 0.003, 48000, false);
        let drop = tone(&mut analyzer, 75., 0.5, 1200, false);
        assert!(drop.bass > quiet.bass * 2.);
        assert!(drop.impact > 0.8);
        assert!(drop.bands[1] > drop.bands[8] * 3.);
        let mut treble = Analyzer::new(48000, 2);
        let high = tone(&mut treble, 4800., 0.4, 4800, false);
        assert!(high.bands[8] > high.bands[1] * 5.);
        let stopped = tone(&mut analyzer, 75., 0., 96000, false);
        assert_eq!(stopped.level, 0.);
        assert_eq!(stopped.impact, 0.);
    }
    #[test]
    fn stereo_phase_does_not_cancel_the_bass() {
        let a = tone(&mut Analyzer::new(48000, 2), 75., 0.4, 4800, false);
        let b = tone(&mut Analyzer::new(48000, 2), 75., 0.4, 4800, true);
        assert!((a.bass - b.bass).abs() < 0.0001);
    }
    #[test]
    fn pcm_decoding_handles_signed_24_bit_and_invalid_float() {
        let mut format = SampleFormat {
            channels: 2,
            rate: 48000,
            stride: 6,
            bytes: 3,
            float: false,
        };
        assert_eq!(format.decode(&[0, 0, 128]), -1.);
        assert!(format.decode(&[255, 255, 127]) > 0.99);
        format.float = true;
        format.bytes = 4;
        assert_eq!(format.decode(&f32::NAN.to_le_bytes()), 0.);
    }
}

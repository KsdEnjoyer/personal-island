use serde::{Deserialize, Serialize};
use std::{
    path::PathBuf,
    time::{Duration, Instant},
};
use tokio::sync::Mutex;

const TTL: i64 = 15 * 60;
const URL: &str = "https://api.open-meteo.com/v1/forecast?latitude=59.9386&longitude=30.3141&current=temperature_2m,apparent_temperature,relative_humidity_2m,is_day,weather_code,wind_speed_10m,wind_direction_10m,precipitation&hourly=temperature_2m,precipitation_probability,weather_code,is_day&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,sunrise,sunset&wind_speed_unit=ms&timeformat=unixtime&timezone=Europe%2FMoscow&forecast_days=7";

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Current {
    pub time: i64,
    pub temperature_2m: f64,
    pub apparent_temperature: f64,
    pub relative_humidity_2m: u8,
    pub is_day: u8,
    pub weather_code: u8,
    pub wind_speed_10m: f64,
    #[serde(default)]
    pub wind_direction_10m: Option<f64>,
    #[serde(default)]
    pub precipitation: Option<f64>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Hour {
    pub time: i64,
    pub temperature: f64,
    pub precipitation: u8,
    pub code: u8,
    pub is_day: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Day {
    pub time: i64,
    pub low: f64,
    pub high: f64,
    pub code: u8,
    #[serde(default)]
    pub precipitation: Option<f64>,
    #[serde(default)]
    pub sunrise: Option<i64>,
    #[serde(default)]
    pub sunset: Option<i64>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WeatherData {
    #[serde(default)]
    pub schema: u8,
    pub city: String,
    pub fetched_at: i64,
    pub current: Current,
    pub hourly: Vec<Hour>,
    pub daily: Vec<Day>,
}
#[derive(Serialize)]
pub struct WeatherState {
    pub data: Option<WeatherData>,
    pub stale: bool,
    pub error: Option<String>,
}
#[derive(Deserialize)]
struct ApiHours {
    time: Vec<i64>,
    temperature_2m: Vec<Option<f64>>,
    precipitation_probability: Vec<Option<u8>>,
    weather_code: Vec<Option<u8>>,
    is_day: Vec<Option<u8>>,
}
#[derive(Deserialize)]
struct ApiDays {
    time: Vec<i64>,
    temperature_2m_min: Vec<Option<f64>>,
    temperature_2m_max: Vec<Option<f64>>,
    weather_code: Vec<Option<u8>>,
    #[serde(default)]
    precipitation_sum: Vec<Option<f64>>,
    #[serde(default)]
    sunrise: Vec<Option<i64>>,
    #[serde(default)]
    sunset: Vec<Option<i64>>,
}
#[derive(Deserialize)]
struct ApiResponse {
    current: Current,
    hourly: ApiHours,
    daily: ApiDays,
}
fn temperature(value: f64) -> bool {
    value.is_finite() && (-100.0..=70.0).contains(&value)
}
fn valid(data: &WeatherData) -> bool {
    data.city == "Санкт-Петербург"
        && data.fetched_at > 0
        && data.current.time > 0
        && temperature(data.current.temperature_2m)
        && temperature(data.current.apparent_temperature)
        && data.current.relative_humidity_2m <= 100
        && data.current.is_day <= 1
        && data.current.wind_speed_10m.is_finite()
        && (0.0..=150.0).contains(&data.current.wind_speed_10m)
        && !data.hourly.is_empty()
        && data.hourly.len() <= 168
        && !data.daily.is_empty()
        && data.daily.len() <= 7
        && data
            .current
            .wind_direction_10m
            .is_none_or(|v| v.is_finite() && (0.0..=360.0).contains(&v))
        && data
            .current
            .precipitation
            .is_none_or(|v| v.is_finite() && (0.0..=1000.0).contains(&v))
        && data
            .hourly
            .iter()
            .all(|hour| hour.time > 0 && temperature(hour.temperature) && hour.precipitation <= 100)
        && data.daily.iter().all(|day| {
            day.time > 0
                && temperature(day.low)
                && temperature(day.high)
                && day.low <= day.high
                && day
                    .precipitation
                    .is_none_or(|v| v.is_finite() && (0.0..=2000.0).contains(&v))
                && day.sunrise.is_none_or(|v| v > 0)
                && day.sunset.is_none_or(|v| v > 0)
        })
}
fn parse(bytes: &[u8], now: i64) -> Result<WeatherData, String> {
    let api: ApiResponse =
        serde_json::from_slice(bytes).map_err(|_| "Сервис погоды вернул неполные данные")?;
    let hourly = api
        .hourly
        .time
        .iter()
        .enumerate()
        .filter_map(|(i, time)| {
            Some(Hour {
                time: *time,
                temperature: *api.hourly.temperature_2m.get(i)?.as_ref()?,
                precipitation: *api.hourly.precipitation_probability.get(i)?.as_ref()?,
                code: *api.hourly.weather_code.get(i)?.as_ref()?,
                is_day: *api.hourly.is_day.get(i)?.as_ref()? == 1,
            })
        })
        .collect();
    let daily = api
        .daily
        .time
        .iter()
        .enumerate()
        .filter_map(|(i, time)| {
            Some(Day {
                time: *time,
                low: *api.daily.temperature_2m_min.get(i)?.as_ref()?,
                high: *api.daily.temperature_2m_max.get(i)?.as_ref()?,
                code: *api.daily.weather_code.get(i)?.as_ref()?,
                precipitation: api.daily.precipitation_sum.get(i).copied().flatten(),
                sunrise: api.daily.sunrise.get(i).copied().flatten(),
                sunset: api.daily.sunset.get(i).copied().flatten(),
            })
        })
        .take(7)
        .collect();
    let data = WeatherData {
        schema: 2,
        city: "Санкт-Петербург".into(),
        fetched_at: now,
        current: api.current,
        hourly,
        daily,
    };
    if !valid(&data) {
        return Err("Сервис погоды вернул неполные данные".into());
    }
    Ok(data)
}

struct Cache {
    data: Option<WeatherData>,
    retry_after: Option<Instant>,
    error: Option<String>,
}
pub struct WeatherService {
    client: reqwest::Client,
    path: PathBuf,
    cache: Mutex<Cache>,
}
impl WeatherService {
    pub fn new(path: PathBuf) -> Result<Self, String> {
        let data = std::fs::metadata(&path)
            .ok()
            .filter(|meta| meta.len() <= 256 * 1024)
            .and_then(|_| std::fs::read(&path).ok())
            .and_then(|bytes| serde_json::from_slice::<WeatherData>(&bytes).ok())
            .filter(valid);
        let client = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(4))
            .timeout(Duration::from_secs(8))
            .redirect(reqwest::redirect::Policy::none())
            .user_agent("PersonalIsland/0.1 (personal weather widget)")
            .build()
            .map_err(|e| e.to_string())?;
        Ok(Self {
            client,
            path,
            cache: Mutex::new(Cache {
                data,
                retry_after: None,
                error: None,
            }),
        })
    }
    async fn fetch(&self) -> Result<WeatherData, String> {
        let mut response = self
            .client
            .get(URL)
            .send()
            .await
            .map_err(|error| {
                eprintln!("Weather request failed: {error:?}");
                "Нет соединения с сервисом погоды"
            })?
            .error_for_status()
            .map_err(|_| "Сервис погоды временно недоступен")?;
        let mut bytes = Vec::new();
        while let Some(chunk) = response
            .chunk()
            .await
            .map_err(|_| "Не удалось загрузить прогноз")?
        {
            if bytes.len() + chunk.len() > 256 * 1024 {
                return Err("Слишком большой ответ сервиса погоды".into());
            }
            bytes.extend_from_slice(&chunk);
        }
        parse(&bytes, chrono::Utc::now().timestamp())
    }
    async fn get(&self) -> WeatherState {
        // Serializes concurrent WebView requests, including during a slow connection.
        let mut cache = self.cache.lock().await;
        let now = chrono::Utc::now().timestamp();
        let fresh = cache.data.as_ref().is_some_and(|data| {
            data.schema >= 2 && data.fetched_at <= now && now - data.fetched_at < TTL
        });
        if fresh {
            return WeatherState {
                data: cache.data.clone(),
                stale: false,
                error: None,
            };
        }
        if cache
            .retry_after
            .is_none_or(|deadline| Instant::now() >= deadline)
        {
            match self.fetch().await {
                Ok(data) => {
                    let temp = self.path.with_extension("json.tmp");
                    if let Ok(bytes) = serde_json::to_vec(&data) {
                        if std::fs::write(&temp, bytes).is_ok() {
                            if let Err(error) = std::fs::rename(&temp, &self.path) {
                                eprintln!("Weather cache write failed: {error}");
                            }
                        }
                    }
                    cache.data = Some(data);
                    cache.error = None;
                    cache.retry_after = None;
                    return WeatherState {
                        data: cache.data.clone(),
                        stale: false,
                        error: None,
                    };
                }
                Err(error) => {
                    cache.error = Some(error);
                    cache.retry_after = Some(Instant::now() + Duration::from_secs(120));
                }
            }
        }
        WeatherState {
            stale: cache.data.is_some(),
            data: cache.data.clone(),
            error: cache.error.clone(),
        }
    }
}
#[tauri::command]
pub async fn get_weather(
    service: tauri::State<'_, WeatherService>,
) -> Result<WeatherState, String> {
    Ok(service.get().await)
}
#[tauri::command]
pub fn open_weather_source() -> Result<(), String> {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        std::process::Command::new("rundll32.exe")
            .args(["url.dll,FileProtocolHandler", "https://open-meteo.com/"])
            .creation_flags(0x08000000)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(target_os = "linux")]
    std::process::Command::new("xdg-open")
        .arg("https://open-meteo.com/")
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    #[ignore = "Contacts the real Open-Meteo API; run explicitly with --ignored"]
    async fn live_spb_api() {
        let temp = tempfile::tempdir().unwrap();
        let service = WeatherService::new(temp.path().join("weather.json")).unwrap();
        let data = service.fetch().await.unwrap();
        assert_eq!(data.daily.len(), 7);
        assert!(data.daily[0].sunrise.is_some());
        assert!(data.daily[0].sunset.is_some());
        assert!(data.current.precipitation.is_some());
        assert_eq!(data.city, "Санкт-Петербург");
    }
    fn fixture() -> Vec<u8> {
        br#"{"current":{"time":1700000000,"temperature_2m":-1.5,"apparent_temperature":-5.0,"relative_humidity_2m":84,"is_day":0,"weather_code":71,"wind_speed_10m":4.2},"hourly":{"time":[1700000000,1700003600],"temperature_2m":[-1.5,null],"precipitation_probability":[70,10],"weather_code":[71,3],"is_day":[0,0]},"daily":{"time":[1699995600],"temperature_2m_min":[-4.0],"temperature_2m_max":[2.0],"weather_code":[71]}}"#.to_vec()
    }
    #[test]
    fn parses_units_and_skips_missing_hours_without_inventing_zeroes() {
        let data = parse(&fixture(), 1700000000).unwrap();
        assert_eq!(data.current.wind_speed_10m, 4.2);
        assert_eq!(data.hourly.len(), 1);
        assert_eq!(data.hourly[0].precipitation, 70);
        assert_eq!(data.daily[0].low, -4.0);
        assert!(parse(br#"{"current":null}"#, 1700000000).is_err());
    }
    #[test]
    fn weekly_metrics_preserve_units_and_reject_invalid_precipitation() {
        let mut json: serde_json::Value = serde_json::from_slice(&fixture()).unwrap();
        json["current"]["wind_direction_10m"] = 315.0.into();
        json["current"]["precipitation"] = 0.3.into();
        json["daily"]["precipitation_sum"] = serde_json::json!([1.2]);
        json["daily"]["sunrise"] = serde_json::json!([1700028000]);
        json["daily"]["sunset"] = serde_json::json!([1700053000]);
        let data = parse(&serde_json::to_vec(&json).unwrap(), 1700000000).unwrap();
        assert_eq!(data.current.wind_direction_10m, Some(315.0));
        assert_eq!(data.current.precipitation, Some(0.3));
        assert_eq!(data.daily[0].precipitation, Some(1.2));
        assert_eq!(data.daily[0].sunrise, Some(1700028000));
        assert_eq!(data.daily[0].sunset, Some(1700053000));
        json["daily"]["precipitation_sum"] = serde_json::json!([-1.0]);
        assert!(parse(&serde_json::to_vec(&json).unwrap(), 1700000000).is_err());
    }
    #[tokio::test]
    async fn fresh_disk_cache_avoids_the_network_and_survives_restart() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("weather.json");
        let data = parse(&fixture(), chrono::Utc::now().timestamp()).unwrap();
        std::fs::write(&path, serde_json::to_vec(&data).unwrap()).unwrap();
        let service = WeatherService::new(path.clone()).unwrap();
        let first = service.get().await;
        assert!(!first.stale);
        assert!(first.error.is_none());
        assert_eq!(first.data.unwrap().current.temperature_2m, -1.5);
        assert!(WeatherService::new(path)
            .unwrap()
            .get()
            .await
            .data
            .is_some());
    }
    #[tokio::test]
    async fn offline_retry_keeps_old_data_and_marks_it_stale() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("weather.json");
        let mut service = WeatherService::new(path).unwrap();
        service.client = reqwest::Client::builder()
            .proxy(reqwest::Proxy::all("http://127.0.0.1:1").unwrap())
            .timeout(Duration::from_millis(300))
            .build()
            .unwrap();
        service.cache.get_mut().data = Some(parse(&fixture(), 1).unwrap());
        let result = service.get().await;
        assert!(result.stale);
        assert!(result.error.is_some());
        assert!(result.data.is_some());
        let deadline = service.cache.lock().await.retry_after;
        assert!(service.get().await.stale);
        assert_eq!(service.cache.lock().await.retry_after, deadline);
    }
}

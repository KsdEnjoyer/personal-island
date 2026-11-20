export type Task = {
  id: number;
  title: string;
  notes: string | null;
  due_at: string | null;
  reminder_at: string | null;
  priority: number;
  status: 'open' | 'done';
  created_at: string;
  completed_at: string | null;
  notification_sent_at: string | null;
};

export type NewTask = {
  title: string;
  notes?: string | null;
  due_at?: string | null;
  reminder_at?: string | null;
  priority?: number;
};

export type ClipboardEntry = { id: number; kind: 'text' | 'image' | 'files'; text: string | null; thumbnail: string | null; width: number | null; height: number | null; pinned: boolean; captured_at: number; files?: { name: string; path: string }[] };
export type ClipboardHistory = { enabled: boolean; entries: ClipboardEntry[] };
export type MediaState = { sessions: { id: string; label: string }[]; session_id: string | null; source: string; title: string; artist: string; artwork: string | null; playing: boolean; position: number; duration: number; can_toggle: boolean; can_previous: boolean; can_next: boolean; can_seek: boolean };
export type IslandShortcut = { key: number; ctrl: boolean; alt: boolean; shift: boolean };
export type WidgetSettings = { shortcut: IslandShortcut; review_interval_minutes: number; shortcut_error?: string | null };
export type WeatherData = {
  city: string; fetched_at: number;
  current: { time: number; temperature_2m: number; apparent_temperature: number; relative_humidity_2m: number; is_day: number; weather_code: number; wind_speed_10m: number; wind_direction_10m?: number | null; precipitation?: number | null };
  hourly: { time: number; temperature: number; precipitation: number; code: number; is_day: boolean }[];
  daily: { time: number; low: number; high: number; code: number; precipitation?: number | null; sunrise?: number | null; sunset?: number | null }[];
};
export type WeatherState = { data: WeatherData | null; stale: boolean; error: string | null };

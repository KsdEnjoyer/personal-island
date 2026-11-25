import { invoke } from '@tauri-apps/api/core';

export const MUSIC_APP_NAMES = { 'yandex-music': 'Яндекс Музыка', 'spotify-app': 'Spotify' } as const;
export type MusicApp = keyof typeof MUSIC_APP_NAMES;
const STORAGE_KEY = 'personal-island.music-source.v1';

export function musicAppId(source: string | null): MusicApp | null {
  return source === 'yandex-music' || source === 'spotify-app' ? source : null;
}

export function openMusicApp(app: MusicApp) {
  return invoke(app === 'spotify-app' ? 'open_spotify' : 'open_yandex_music');
}

export function loadMediaPreference(): string | null {
  try {
    return musicAppId(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

export function saveMediaPreference(source: string | null) {
  try {
    if (source && musicAppId(source)) localStorage.setItem(STORAGE_KEY, source);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // The current source still works when local storage is unavailable.
  }
}

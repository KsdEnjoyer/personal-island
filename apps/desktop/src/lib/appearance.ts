export type IslandAppearance = 'island' | 'portrait';

export type AppearanceSettings = {
  style: IslandAppearance;
  liquid: boolean;
  equalizer: boolean;
};

const STORAGE_KEY = 'personal-island.appearance.v1';
const defaults: AppearanceSettings = { style: 'island', liquid: true, equalizer: true };

export function loadAppearance(): AppearanceSettings {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    return {
      style: saved?.style === 'portrait' ? 'portrait' : 'island',
      liquid: typeof saved?.liquid === 'boolean' ? saved.liquid : defaults.liquid,
      equalizer: typeof saved?.equalizer === 'boolean' ? saved.equalizer : defaults.equalizer,
    };
  } catch {
    return { ...defaults };
  }
}

export function saveAppearance(settings: AppearanceSettings): boolean {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    return true;
  } catch {
    return false;
  }
}

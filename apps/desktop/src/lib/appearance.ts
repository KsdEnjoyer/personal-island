export type IslandAppearance = 'island' | 'portrait';

export type AppearanceSettings = {
  style: IslandAppearance;
  liquid: boolean;
};

const STORAGE_KEY = 'personal-island.appearance.v1';
const defaults: AppearanceSettings = { style: 'island', liquid: true };

export function loadAppearance(): AppearanceSettings {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    return {
      style: saved?.style === 'portrait' ? 'portrait' : 'island',
      liquid: typeof saved?.liquid === 'boolean' ? saved.liquid : defaults.liquid,
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

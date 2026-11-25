import type { IslandShortcut, WidgetSettings } from '../types';
export const defaultShortcut: IslandShortcut = { key: 192, ctrl: false, alt: false, shift: false };
export const linuxDefaultShortcut: IslandShortcut = { key: 73, ctrl: true, alt: true, shift: false };
export type ShortcutMode = 'windows' | 'x11' | 'portal';
export const defaultWidgetSettings: WidgetSettings = { shortcut: defaultShortcut, suppress_shortcut_character: false, review_interval_minutes: 30 };
export function shortcutLabel(shortcut: IslandShortcut): string {
  const key = shortcut.key === 192 ? 'Ё / `' : shortcut.key === 32 ? 'Пробел' : shortcut.key >= 112 && shortcut.key <= 135 ? `F${shortcut.key - 111}` : String.fromCharCode(shortcut.key);
  return [shortcut.ctrl && 'Ctrl', shortcut.alt && 'Alt', shortcut.shift && 'Shift', key].filter(Boolean).join(' + ');
}
export function capturedShortcut(event: KeyboardEvent, windows = true): IslandShortcut | null {
  let key = 0;
  if (/^Key[A-Z]$/.test(event.code)) key = event.code.charCodeAt(3);
  else if (/^Digit[0-9]$/.test(event.code)) key = event.code.charCodeAt(5);
  else if (/^F([1-9]|1[0-9]|2[0-4])$/.test(event.code)) key = 111 + Number(event.code.slice(1));
  else if (event.code === 'Backquote') key = 192;
  else if (event.code === 'Space') key = 32;
  if (!key || event.metaKey || (windows && key === 123)) return null;
  if (!event.ctrlKey && !event.altKey && !(key >= 112 && key <= 135) && !(windows && key === 192)) return null;
  if (key === 192 && event.shiftKey && !event.ctrlKey && !event.altKey) return null;
  return { key, ctrl: event.ctrlKey, alt: event.altKey, shift: event.shiftKey };
}
export function reviewLabel(minutes: number): string {
  return minutes === 0 ? 'Автопоказ выключен' : minutes === 30 ? 'Автопоказ · в :00 и :30' : `Автопоказ · каждые ${minutes} мин`;
}

/** Small explicit Russian date grammar; unsupported phrases require the date picker. */
export function parseReminder(text: string, now = new Date()): { title: string; at: Date } | null {
  const relative = text.match(/\s+через\s+(\d{1,3})\s*(мин(?:ут[уы]?)?|ч(?:ас(?:а|ов)?)?)\.?\s*$/iu);
  if (relative) {
    const count = Number(relative[1]);
    if (!count) return null;
    const at = new Date(now.getTime() + count * (/^ч/iu.test(relative[2]) ? 3600000 : 60000));
    const title = text.slice(0, relative.index).trim();
    return title ? { title, at } : null;
  }
  const absolute = text.match(/\s+(сегодня|завтра)\s+в\s+(\d{1,2})(?::(\d{2}))?\s*$/iu);
  if (!absolute || Number(absolute[2]) > 23 || Number(absolute[3] || 0) > 59) return null;
  const at = new Date(now.getFullYear(), now.getMonth(), now.getDate() + (absolute[1].toLowerCase() === 'завтра' ? 1 : 0), Number(absolute[2]), Number(absolute[3] || 0));
  const title = text.slice(0, absolute.index).trim();
  return title && at > now ? { title, at } : null;
}

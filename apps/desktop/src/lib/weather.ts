export const degrees = (value: number) => `${Math.round(value) > 0 ? '+' : ''}${Math.round(value)}°`;
export const spbTime = (timestamp: number, options: Intl.DateTimeFormatOptions) => new Date(timestamp * 1000).toLocaleString('ru-RU', { ...options, timeZone: 'Europe/Moscow' });
export function weatherLabel(code: number, isDay = true) {
  if (code === 0) return isDay ? 'Ясно' : 'Ясная ночь';
  if (code === 1) return 'Преимущественно ясно';
  if (code === 2) return 'Переменная облачность';
  if (code === 3) return 'Пасмурно';
  if ([45, 48].includes(code)) return 'Туман';
  if ([51, 53, 55].includes(code)) return 'Морось';
  if ([56, 57, 66, 67].includes(code)) return 'Ледяные осадки';
  if ([61, 63, 65].includes(code)) return 'Дождь';
  if ([71, 73, 75, 77, 85, 86].includes(code)) return 'Снег';
  if ([80, 81, 82].includes(code)) return 'Ливень';
  if ([95, 96, 97, 99].includes(code)) return 'Гроза';
  return 'Погода';
}

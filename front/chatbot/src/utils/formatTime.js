/**
 * Время для отображения (часы:минуты). Принимает Date или строку ISO.
 */
export function formatTime(dateInput) {
  try {
    const d = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

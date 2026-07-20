/**
 * Format a timestamp for display (local timezone).
 * Accepts epoch ms, epoch seconds, Date, or ISO string.
 */
export function formatDateTime(value) {
  if (value == null || value === '') return '—';
  let date;
  if (value instanceof Date) {
    date = value;
  } else if (typeof value === 'number') {
    date = new Date(value < 1e12 ? value * 1000 : value);
  } else {
    const n = Number(value);
    if (Number.isFinite(n) && String(value).trim() !== '') {
      date = new Date(n < 1e12 ? n * 1000 : n);
    } else {
      date = new Date(value);
    }
  }
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

/** @deprecated Use formatDateTime */
export const formatBeijingDateTime = formatDateTime;

export default formatDateTime;

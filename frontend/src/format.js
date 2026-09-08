/**
 * Display formatting.
 *
 * The API sends every timestamp as UTC with a trailing "Z". Nothing here ever
 * assumes a timezone: `new Date()` parses the instant and the Intl formatters
 * render it in whatever zone the browser reports, which is exactly the
 * "store UTC, show local" split the app is built around.
 */

/** The viewer's IANA timezone, e.g. "America/New_York". */
export const browserTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

export function parseUtc(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const dateFormat = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "numeric",
});

/** Absolute local time, e.g. "Sep 5, 2026, 1:24 PM". */
export function formatDateTime(value) {
  const date = parseUtc(value);
  return date ? dateTimeFormat.format(date) : "—";
}

export function formatDate(value) {
  const date = parseUtc(value);
  return date ? dateFormat.format(date) : "—";
}

const relativeFormat = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const RELATIVE_UNITS = [
  ["year", 31536000],
  ["month", 2592000],
  ["week", 604800],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];

/** "3 hours ago" / "in 12 minutes". */
export function formatRelative(value) {
  const date = parseUtc(value);
  if (!date) return "never";
  const seconds = (date.getTime() - Date.now()) / 1000;
  const magnitude = Math.abs(seconds);
  if (magnitude < 45) return "just now";
  for (const [unit, size] of RELATIVE_UNITS) {
    if (magnitude >= size) {
      return relativeFormat.format(Math.round(seconds / size), unit);
    }
  }
  return relativeFormat.format(Math.round(seconds), "second");
}

/** Both forms: relative for scanning, absolute in the tooltip for precision. */
export function timeTitle(value) {
  const date = parseUtc(value);
  if (!date) return "";
  return `${dateTimeFormat.format(date)} (${browserTimeZone})`;
}

export function formatMoney(value, currency = "USD") {
  if (value === null || value === undefined) return "Call for price";
  const formatter = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency || "USD",
    // Whole dollars unless the vendor actually quoted cents.
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    maximumFractionDigits: 2,
  });
  return formatter.format(value);
}

export function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / 1024 ** index;
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

/** "every 12 hours" style text for a scan interval given in minutes. */
export function formatInterval(minutes) {
  if (!minutes) return "—";
  if (minutes < 60) return `${minutes} min`;
  // Weeks before days: a fortnightly scan reading "14 days" is arithmetic
  // rather than a cadence, and the select box offers it as "Every 2 weeks".
  if (minutes % 10080 === 0) {
    const weeks = minutes / 10080;
    return weeks === 1 ? "1 week" : `${weeks} weeks`;
  }
  if (minutes % 1440 === 0) {
    const days = minutes / 1440;
    return days === 1 ? "1 day" : `${days} days`;
  }
  if (minutes % 60 === 0) {
    const hours = minutes / 60;
    return hours === 1 ? "1 hour" : `${hours} hours`;
  }
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}m ${rest}s`;
}

/**
 * How long is left, phrased as a wait rather than a measurement.
 *
 * Deliberately not formatDuration: that one reports what something took, to a
 * tenth of a second, which is the wrong register for "come back later". Nobody
 * wants to be told to wait 299.0 seconds.
 */
export function formatCountdown(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  const minutes = Math.round(total / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

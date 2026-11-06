export const NPT = "Asia/Kathmandu";

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const HAS_ZONE = /(Z|[+-]\d{2}:?\d{2})$/;

// The API sends naive NPT timestamps ("2026-11-05T11:01:05.123", the DB
// stores naive NPT). new Date() would read those as the *viewer's* local
// time, so outside Nepal every time on the dashboard was shifted; pin them
// to +05:45 instead. Plain dates ("2026-11-05") are pinned to NPT noon so
// no timezone can roll them onto another day.
export function parseNpt(value: string | null | undefined): Date | null {
  if (!value) return null;
  let s = String(value);
  if (DATE_ONLY.test(s)) s = `${s}T12:00:00+05:45`;
  else if (!HAS_ZONE.test(s)) s = `${s}+05:45`;
  const dt = new Date(s);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

export function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

// 4.62B / 345.1M / 12.3K -- for NPR turnover and share counts.
export function formatCompact(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("en-US", { notation: "compact", maximumFractionDigits: digits });
}

export function formatPct(value, digits = 2, signed = false) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const n = Number(value);
  return `${signed && n > 0 ? "+" : ""}${n.toFixed(digits)}%`;
}

export function formatDate(dateString: string | null | undefined): string {
  const dt = parseNpt(dateString);
  if (!dt) return "-";
  if (DATE_ONLY.test(String(dateString))) return formatDay(dateString);
  return dt.toLocaleString("en-US", {
    timeZone: NPT,
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }) + " NPT";
}

export function formatDay(dateString: string | null | undefined): string {
  const dt = parseNpt(dateString);
  if (!dt) return "-";
  return dt.toLocaleDateString("en-US", { timeZone: NPT, year: "numeric", month: "short", day: "2-digit" });
}

export function shortTime(dateString: string | null | undefined): string {
  const dt = parseNpt(dateString);
  if (!dt) return "-";
  return dt.toLocaleTimeString("en-US", { timeZone: NPT, hour: "2-digit", minute: "2-digit", hour12: false });
}

// "Nov 05 11:00" -- axis ticks for windows spanning several sessions.
export function shortDateTime(dateString: string | null | undefined): string {
  const dt = parseNpt(dateString);
  if (!dt) return "-";
  const day = dt.toLocaleDateString("en-US", { timeZone: NPT, month: "short", day: "2-digit" });
  return `${day} ${shortTime(dateString)}`;
}

// "Nov 2026" / "Nov 05" -- axis ticks for daily series, by span.
export function axisDay(dateString: string | null | undefined, longSpan = false): string {
  const dt = parseNpt(dateString);
  if (!dt) return "-";
  return longSpan
    ? dt.toLocaleDateString("en-US", { timeZone: NPT, month: "short", year: "numeric" })
    : dt.toLocaleDateString("en-US", { timeZone: NPT, month: "short", day: "2-digit" });
}

// "3 min ago" / "2 h ago" / "4 d ago".
export function timeAgo(dateString: string | null | undefined): string {
  const dt = parseNpt(dateString);
  if (!dt) return "-";
  const minutes = Math.round((Date.now() - dt.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
}

export function trendColor(value) {
  if (value > 0) return "text-emerald-300";
  if (value < 0) return "text-rose-300";
  return "text-slate-300";
}

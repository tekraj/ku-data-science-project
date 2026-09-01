export const NPT = "Asia/Kathmandu";

export function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

export function formatDate(dateString: string | null | undefined): string {
  if (!dateString) return "-";
  const dt = new Date(dateString);
  if (Number.isNaN(dt.getTime())) return "-";
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

export function shortTime(dateString: string | null | undefined): string {
  if (!dateString) return "-";
  const dt = new Date(dateString);
  if (Number.isNaN(dt.getTime())) return "-";
  return dt.toLocaleTimeString("en-US", { timeZone: NPT, hour: "2-digit", minute: "2-digit", hour12: false });
}

export function trendColor(value) {
  if (value > 0) return "text-emerald-300";
  if (value < 0) return "text-rose-300";
  return "text-slate-300";
}

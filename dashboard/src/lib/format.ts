// Strict money / R / percent formatting — tabular, signed, honest (frontend_v2 §2.2).

const DASH = "—";

export function fmtINR(v: number | null | undefined, dp = 0): string {
  if (v == null || Number.isNaN(v)) return DASH;
  const s = new Intl.NumberFormat("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp }).format(Math.abs(v));
  return (v < 0 ? "-₹" : "₹") + s;
}

export function fmtNum(v: number | null | undefined, dp = 2): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp }).format(v);
}

export function fmtPct(v: number | null | undefined, dp = 2, signed = true): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return (signed && v >= 0 ? "+" : "") + v.toFixed(dp) + "%";
}

export function fmtR(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return (v >= 0 ? "+" : "") + v.toFixed(1) + "R";
}

export function pnlClass(v: number | null | undefined): string {
  if (v == null || v === 0 || Number.isNaN(v)) return "text-text-lo";
  return v > 0 ? "text-long" : "text-short";
}

export function fmtTimeIST(iso: string | null | undefined): string {
  if (!iso) return DASH;
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    }).format(new Date(iso));
  } catch {
    return DASH;
  }
}

export function fmtAge(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms) || ms < 0) return DASH;
  const m = Math.floor(ms / 60000);
  if (m < 60) return m + "m";
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

export function clockIST(d = new Date()): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(d);
}

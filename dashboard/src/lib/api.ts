// REST client for the Aegis API (frontend_v2 Appendix B). Single source of fetch logic.
import type { Account, Health, MarketRow, PnlToday, Position, Signal, Sleeve } from "./types";

const BASE = "/api";

// Attach the operator bearer token (set at the LoginGate) when present. Harmless
// when the backend runs with auth disabled (API_AUTH_TOKEN empty).
function authHeaders(json: boolean): Record<string, string> | undefined {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  const tok = typeof localStorage !== "undefined" ? localStorage.getItem("aegis.token") : null;
  if (tok) h["Authorization"] = `Bearer ${tok}`;
  return Object.keys(h).length ? h : undefined;
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: authHeaders(body !== undefined),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return (await res.json()) as T;
}

const get = <T>(p: string) => req<T>("GET", p);

export const api = {
  account: () => get<Account>("/account"),
  pnlToday: () => get<PnlToday>("/pnl/today"),
  positions: () => get<Position[]>("/positions"),
  sleeves: () => get<Sleeve[]>("/sleeves"),
  risk: () => get<any>("/risk"),
  signals: (filter?: string) => get<Signal[]>(`/signals${filter ? `?filter=${filter}` : ""}`),
  rejections: () => get<any>("/signals/rejections"),
  market: () => get<MarketRow[]>("/market"),
  breadth: () => get<any>("/breadth"),
  chart: (instrument: string, interval = "5m") =>
    get<any>(`/chart/${encodeURIComponent(instrument)}?interval=${interval}`),
  optionchain: (u: string, expiry?: string) =>
    get<any>(`/optionchain/${encodeURIComponent(u)}${expiry ? `?expiry=${expiry}` : ""}`),
  analytics: (period = "all") => get<any>(`/analytics?period=${period}`),
  audit: (params?: { limit?: number; offset?: number; event_type?: string; correlation_id?: string }) => {
    const q = new URLSearchParams();
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.offset) q.set("offset", String(params.offset));
    if (params?.event_type) q.set("event_type", params.event_type);
    if (params?.correlation_id) q.set("correlation_id", params.correlation_id);
    const s = q.toString();
    return get<any[]>(`/audit${s ? `?${s}` : ""}`);
  },
  reconstruct: (cid: string) => get<any>(`/audit/${cid}`),
  config: () => get<any>("/config"),
  health: () => get<Health>("/health"),
  backtests: () => get<any[]>("/backtests"),
  backtestRun: (id: number) => get<any>(`/backtest/${id}`),
  startBacktest: (body: {
    symbols: string[]; from_date: string; to_date: string;
    sleeve?: string; starting_capital?: number; per_trade_pct?: number;
  }) => req<any>("POST", "/backtest", body),
  research: () => get<any>("/research"),
  researchDataset: () => get<any>("/research/dataset"),
  researchDiscrimination: () => get<any>("/research/discrimination"),
  trainMeta: (body?: { name?: string; min_samples?: number }) => req<any>("POST", "/research/train", body ?? {}),
  prelive: () => get<any>("/prelive-checklist"),
  // F&O research on the curated lake (Pillars 1-5)
  fnoLake: (start = "2026-01-01") => get<any>(`/fno/lake?start=${start}`),
  fnoAnalytics: (u: string, start = "2026-01-01") =>
    get<any>(`/fno/analytics?underlying=${encodeURIComponent(u)}&start=${start}`),
  fnoFeatures: (u: string, start = "2026-01-01") =>
    get<any>(`/fno/features?underlying=${encodeURIComponent(u)}&start=${start}`),
  fnoBacktest: (u: string, start = "2026-01-01") =>
    get<any>(`/fno/backtest?underlying=${encodeURIComponent(u)}&start=${start}`),
  layouts: () => get<any[]>("/layouts"),

  // actions — all UI-guarded
  pause: (paused: boolean) => req("POST", "/controls/pause", { paused }),
  flatten: () => req("POST", "/controls/flatten", { confirm: true }),
  sleeveToggle: (s: string, enabled: boolean) => req("POST", `/controls/sleeve/${s}`, { enabled }),
  setMode: (mode: string, confirm_token?: string) => req("POST", "/controls/mode", { mode, confirm_token }),
  ksReset: () => req("POST", "/controls/killswitch/reset", { confirm: true }),
  closePosition: (id: string) => req("POST", `/positions/${id}/close`, { confirm: true }),
  modifyPosition: (id: string, stop?: number, target?: number) =>
    req("POST", `/positions/${id}/modify`, { stop, target }),
  putConfig: (path: string, value: number) => req("PUT", "/config", { path, value }),
  putLayout: (name: string, layout: unknown) => req("PUT", "/layouts", { name, layout }),
};

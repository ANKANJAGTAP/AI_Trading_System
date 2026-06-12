// API contract types (frontend_v2 Appendix B). Indicative; loose where the backend
// payload is rich — the dashboard tolerates extra fields.

export type Mode = "simulated_fill" | "live";

export interface Account {
  live_capital: number; available_margin: number; used_margin: number; deployed_pct: number; mode: Mode;
}

export interface PnlToday {
  realized: number; unrealized: number; net: number; pct_of_capital: number;
  killswitch_limit: number; killswitch_used: number; equity_curve: { ts: string; value: number }[];
}

export interface GateNode { name: string; pass: boolean; score: number }

export interface Signal {
  id: number; correlation_id: string; ts: string; instrument: string; sleeve: string; setup: string | null;
  gates: GateNode[]; confidence: number; decision: string; action?: string; reject_gate?: string | null;
  reason?: string | null; llm?: { sentiment: string; event_risk: string; veto: boolean; reason: string } | null;
}

export interface Position {
  id: number | string; instrument: string; sleeve: string; side: string; qty: number;
  entry: number; ltp: number; stop: number; target: number; R_at_risk: number; R_multiple: number;
  unrealized: number; mae: number; mfe: number; spark: number[]; state: string; opened_at?: string | null;
  structure?: { net_max_loss: number; greeks: Record<string, number> | null; legs: any[] };
}

export interface Sleeve {
  sleeve: string; cap_pct: number; deployed: number; margin_headroom: number; day_pnl: number;
  cum_pnl: number; curve: { ts: string; value: number }[]; wins: number; losses: number; avg_R: number;
  enabled: boolean; positions: number;
}

export interface Health {
  feed: string; feed_last_tick: string | null; token: string; token_expiry: string | null;
  last_reconcile: string | null; rate_limit_headroom: number | null; loop_heartbeat: string | null;
  error_rate: number; session_state: string; mode: Mode; paused: boolean; kill_switch_active: boolean;
}

export interface MarketRow {
  instrument: string; key: string; token: number; sleeves: string[]; ltp: number | null; chg: number | null;
  chg_pct: number | null; spark: number[]; rvol: number | null; vwap_dist: number | null;
  or_state: string | null; vol_vs_avg: number | null; day_range: { lo: number; hi: number; pos: number | null } | null;
  oi: number | null; iv: number | null; iv_rank: number | null; pcr: number | null;
  fno_ban: boolean; signal_state: string | null; eligible: boolean;
}

// WS event envelope
export interface WsEvent<T = any> { type: string; payload: T; ts: string }

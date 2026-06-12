// Command Center (frontend_v2 §4.1) — in one screen: health, capital, risk, market
// context, today's stats, equity curve, sleeves, and the live activity feed.
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useState } from "react";
import { api } from "@/lib/api";
import { EquityChart } from "@/components/charts/EquityChart";
import { TickNum } from "@/components/TickNum";
import { InlineGauge, Sparkline, StatusDot } from "@/components/viz";
import { fmtINR, fmtNum, fmtPct, fmtR, fmtTimeIST, pnlClass } from "@/lib/format";
import { useStore } from "@/store/store";

function Panel({ title, right, span, children }: { title?: string; right?: ReactNode; span: number; children: ReactNode }) {
  return (
    <div className="flex min-h-0 flex-col rounded-panel border bg-surface" style={{ gridColumn: `span ${span}` }}>
      {title && (
        <div className="flex items-center justify-between border-b px-3 py-1.5">
          <span className="eyebrow">{title}</span>
          {right}
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto p-3">{children}</div>
    </div>
  );
}

function Stat({ label, value, cls, sub }: { label: string; value: ReactNode; cls?: string; sub?: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="eyebrow">{label}</span>
      <span className={"mono text-[15px] " + (cls ?? "text-text-hi")}>{value}</span>
      {sub != null && <span className="mono text-micro text-text-faint">{sub}</span>}
    </div>
  );
}

export function CommandCenter() {
  const stale = useStore((s) => s.connection) !== "open";
  const activity = useStore((s) => s.activity);
  const openInspector = useStore((s) => s.openInspector);
  const [period, setPeriod] = useState<"today" | "all">("today");

  const pnl = useQuery({ queryKey: ["pnl"], queryFn: api.pnlToday, refetchInterval: 4000 });
  const account = useQuery({ queryKey: ["account"], queryFn: api.account, refetchInterval: 6000 });
  const risk = useQuery({ queryKey: ["risk"], queryFn: api.risk, refetchInterval: 8000 });
  const sleeves = useQuery({ queryKey: ["sleeves"], queryFn: api.sleeves, refetchInterval: 8000 });
  const market = useQuery({ queryKey: ["market"], queryFn: api.market, refetchInterval: 5000 });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 6000 });
  const breadth = useQuery({ queryKey: ["breadth"], queryFn: api.breadth, refetchInterval: 15000 });
  const today = useQuery({ queryKey: ["analytics", "today"], queryFn: () => api.analytics("today"), refetchInterval: 10000 });
  const allA = useQuery({ queryKey: ["analytics", "all"], queryFn: () => api.analytics("all"), enabled: period === "all", refetchInterval: 20000 });

  const p = pnl.data;
  const k = today.data?.kpis;
  const ksPct = p && p.killswitch_limit ? Math.min(1, p.killswitch_used / p.killswitch_limit) : 0;
  const ksColor = ksPct >= 1 ? "var(--short)" : ksPct >= 0.75 ? "var(--warn)" : "var(--long)";
  const curve = period === "today" ? p?.equity_curve ?? [] : allA.data?.equity_curve ?? [];
  const sc = stale ? "stale" : "";
  const idx = (n: string) => market.data?.find((r) => r.instrument.toUpperCase().includes(n));
  const nifty = idx("NIFTY 50");
  const regime = nifty?.vwap_dist == null ? "—" : nifty.vwap_dist > 0.1 ? "trending up" : nifty.vwap_dist < -0.1 ? "trending down" : "choppy";

  const hd = (label: string, status: "ok" | "warn" | "down", detail: string) => (
    <div className="flex items-center justify-between py-1">
      <StatusDot status={status} label={label} />
      <span className="mono text-micro text-text-faint">{detail}</span>
    </div>
  );

  return (
    <div className="grid h-full gap-3 overflow-auto p-3" style={{ gridTemplateColumns: "repeat(12, minmax(0,1fr))", gridAutoRows: "min-content" }}>
      {/* HERO + KILL-SWITCH */}
      <div className={"flex flex-col gap-2 rounded-panel border bg-surface p-4 " + sc} style={{ gridColumn: "span 4" }}>
        <span className="eyebrow">Today · Net P&amp;L</span>
        <div className={"mono font-semibold " + pnlClass(p?.net)} style={{ fontSize: 44, lineHeight: 1 }}>
          <TickNum value={p?.net} fmt={(v) => fmtINR(v)} />
        </div>
        <div className="flex gap-4 text-dense">
          <span className="text-text-lo">real <span className={"mono " + pnlClass(p?.realized)}>{fmtINR(p?.realized)}</span></span>
          <span className="text-text-lo">unreal <span className={"mono " + pnlClass(p?.unrealized)}>{fmtINR(p?.unrealized)}</span></span>
          <span className="text-text-lo">of cap <span className={"mono " + pnlClass(p?.net)}>{fmtPct(p?.pct_of_capital)}</span></span>
        </div>
        <div className="mt-2">
          <div className="mb-1 flex items-center justify-between text-micro">
            <span className="eyebrow">Kill-switch</span>
            <span className="mono text-text-lo">{fmtINR(p?.killswitch_used)} / {fmtINR(p?.killswitch_limit)}</span>
          </div>
          <div className="h-2.5 w-full overflow-hidden rounded-full" style={{ background: "var(--surface-inset)" }}>
            <div className="h-full rounded-full" style={{ width: `${ksPct * 100}%`, background: ksColor, transition: "width .4s ease" }} />
          </div>
        </div>
      </div>

      {/* MARKET CONTEXT */}
      <Panel title="Market Context" span={8} right={<span className="eyebrow">regime · {regime}</span>}>
        <div className="flex flex-wrap gap-5">
          {["NIFTY 50", "NIFTY BANK"].map((name) => {
            const r = idx(name);
            return (
              <div key={name} className={"flex items-center gap-2 " + sc}>
                <span className="eyebrow">{name}</span>
                <span className="mono text-[15px]"><TickNum value={r?.ltp} fmt={(v) => fmtNum(v, 1)} /></span>
                <span className={"mono text-dense " + pnlClass(r?.chg_pct)}>{fmtPct(r?.chg_pct)}</span>
                <Sparkline data={r?.spark ?? []} w={56} h={16} />
              </div>
            );
          })}
          <div className={"flex items-center gap-2 " + sc}>
            <span className="eyebrow">VIX rank</span>
            <span className="mono text-[15px]">{fmtNum(market.data?.[0]?.iv_rank, 0)}</span>
          </div>
          <div className={"flex items-center gap-2 " + sc} title="advances / declines across the tracked universe">
            <span className="eyebrow">breadth</span>
            <span className="mono text-[15px]">
              <span className="text-long">{breadth.data?.advances ?? "—"}</span>
              <span className="text-text-faint"> / </span>
              <span className="text-short">{breadth.data?.declines ?? "—"}</span>
            </span>
            {breadth.data?.bias && (
              <span className="eyebrow" style={{ color: breadth.data.bias === "bullish" ? "var(--long)" : breadth.data.bias === "bearish" ? "var(--short)" : "var(--text-lo)" }}>
                {breadth.data.bias}
              </span>
            )}
          </div>
        </div>
      </Panel>

      {/* STAT GRID */}
      <Panel title="Today" span={8}>
        <div className="grid grid-cols-4 gap-x-4 gap-y-3">
          <Stat label="trades" value={k?.trades ?? 0}
            sub={k ? `${Math.round((k.win_rate / 100) * k.trades)}W / ${k.trades - Math.round((k.win_rate / 100) * k.trades)}L` : undefined} />
          <Stat label="hit rate" value={fmtPct(k?.win_rate, 0, false)} />
          <Stat label="expectancy" value={fmtNum(k?.expectancy_R, 2) + "R"} cls={pnlClass(k?.expectancy_R)} />
          <Stat label="profit factor" value={fmtNum(k?.profit_factor, 2)} />
          <Stat label="open R / max" value={`${fmtNum(risk.data?.open_R, 0)} / ${fmtNum(risk.data?.portfolio_limit_R, 0)}`} />
          <Stat label="positions" value={`${risk.data?.num_positions ?? 0} / ${risk.data?.max_positions ?? 0}`} />
          <Stat label="largest win" value={fmtINR(k?.largest_win)} cls="text-long" />
          <Stat label="largest loss" value={fmtINR(k?.largest_loss)} cls="text-short" />
          <Stat label="avail margin" value={fmtINR(account.data?.available_margin)}
            sub={<InlineGauge value={account.data?.used_margin ?? 0} max={account.data?.live_capital ?? 1} w={100} />} />
          <Stat label="deployed" value={fmtPct(account.data?.deployed_pct, 1, false)} />
          <Stat label="leverage" value={fmtNum(risk.data?.leverage_x, 2) + "x"} />
          <Stat label="heat" value={fmtPct(risk.data?.heat_pct, 0, false)} />
        </div>
      </Panel>

      {/* SYSTEM HEALTH */}
      <Panel title="System Health" span={4}>
        <div className="flex flex-col">
          {hd("feed", health.data?.feed === "stale" || health.data?.feed === "unknown" ? "warn" : "ok", fmtTimeIST(health.data?.feed_last_tick))}
          {hd("token", health.data?.token === "ok" ? "ok" : "down", fmtTimeIST(health.data?.token_expiry))}
          {hd("loop", health.data?.loop_heartbeat ? "ok" : "warn", fmtTimeIST(health.data?.loop_heartbeat))}
          {hd("reconcile", health.data?.last_reconcile ? "ok" : "warn", fmtTimeIST(health.data?.last_reconcile))}
          {hd("error rate", (health.data?.error_rate ?? 0) > 0.1 ? "warn" : "ok", fmtPct((health.data?.error_rate ?? 0) * 100, 1, false))}
          {hd("kill-switch", health.data?.kill_switch_active ? "down" : "ok", health.data?.kill_switch_active ? "ACTIVE" : "armed")}
        </div>
      </Panel>

      {/* EQUITY CURVE */}
      <Panel title="Equity Curve" span={8} right={
        <div className="flex gap-1">
          {(["today", "all"] as const).map((pp) => (
            <button key={pp} onClick={() => setPeriod(pp)}
              className={"rounded-control border px-1.5 py-0.5 text-micro " + (period === pp ? "text-text-hi" : "text-text-lo")}
              style={period === pp ? { borderColor: "var(--brand)" } : undefined}>{pp}</button>
          ))}
        </div>
      }>
        <EquityChart data={curve} height={132} className={sc} />
      </Panel>

      {/* SLEEVE STRIP */}
      <Panel title="Sleeves" span={12}>
        <div className="grid grid-cols-4 gap-3">
          {(sleeves.data ?? []).map((sl) => (
            <div key={sl.sleeve} className={"flex flex-col gap-1 rounded-control border bg-surface-inset p-2 " + sc}>
              <div className="flex items-center justify-between">
                <span className="eyebrow">{sl.sleeve}</span>
                <StatusDot status={sl.enabled ? "ok" : "warn"} />
              </div>
              <InlineGauge value={sl.deployed} max={(sl.deployed + sl.margin_headroom) || 1} w={140} />
              <div className="flex items-center justify-between">
                <span className={"mono text-dense " + pnlClass(sl.day_pnl)}>{fmtINR(sl.day_pnl)}</span>
                <Sparkline data={(sl.curve ?? []).map((c) => c.value)} w={64} h={14} />
              </div>
              <div className="flex justify-between text-micro text-text-faint">
                <span>{sl.positions} pos</span>
                <span>W{sl.wins}/L{sl.losses} · {fmtR(sl.avg_R)}</span>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* ACTIVITY FEED */}
      <Panel title="Activity" span={12}>
        {activity.length === 0 ? (
          <div className="py-6 text-center text-dense text-text-faint">No activity yet — the engine is watching for qualifying setups.</div>
        ) : (
          <div className="flex flex-col">
            {activity.slice(0, 40).map((it) => {
              const color = it.kind === "alert" ? "var(--warn)" : it.kind === "order" ? "var(--brand)" : "var(--text-lo)";
              const label = it.kind === "order" ? `${it.data?.instrument ?? ""} ${it.data?.status ?? ""}`
                : it.kind === "alert" ? it.data?.message ?? "alert"
                  : `${it.data?.instrument ?? ""} ${it.data?.status ?? ""}${it.data?.reason ? " · " + it.data.reason : ""}`;
              return (
                <button key={it.id} onClick={() => openInspector(it.kind, it.data)}
                  className="flex items-center gap-2 border-b border-line py-1 text-left text-dense hover:bg-surface-raised">
                  <span className="inline-block rounded-full" style={{ width: 6, height: 6, background: color }} />
                  <span className="eyebrow w-14 shrink-0">{it.kind}</span>
                  <span className="flex-1 truncate text-text-lo">{label}</span>
                  <span className="mono text-micro text-text-faint">{fmtTimeIST(it.ts)}</span>
                </button>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}

// Analytics (frontend_v2 §4.9) — is the edge real, from REAL trades only. Equity +
// drawdown curves, KPIs (expectancy in R), breakdowns, R/hold-time histograms,
// hour/weekday performance heatmaps; sim vs live clearly labeled.
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useState } from "react";
import { api } from "@/lib/api";
import { EquityChart } from "@/components/charts/EquityChart";
import { HeatCell } from "@/components/viz";
import { fmtINR, fmtNum, fmtPct, pnlClass } from "@/lib/format";
import { useStore } from "@/store/store";

function P({ title, span, children }: { title: string; span: number; children: ReactNode }) {
  return (
    <div className="flex min-h-0 flex-col rounded-panel border bg-surface" style={{ gridColumn: `span ${span}` }}>
      <div className="border-b px-3 py-1.5 eyebrow">{title}</div>
      <div className="min-h-0 flex-1 overflow-auto p-3">{children}</div>
    </div>
  );
}
function K({ label, value, cls }: { label: string; value: ReactNode; cls?: string }) {
  return <div className="flex flex-col gap-0.5"><span className="eyebrow">{label}</span><span className={"mono text-[15px] " + (cls ?? "text-text-hi")}>{value}</span></div>;
}
function Breakdown({ rows }: { rows: any[] }) {
  if (!rows || rows.length === 0) return <span className="text-dense text-text-faint">no trades</span>;
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.pnl)));
  return (
    <div className="flex flex-col gap-1 text-dense">
      {rows.map((r) => (
        <div key={r.key} className="flex items-center gap-2">
          <span className="w-24 shrink-0 truncate text-text-lo">{r.key}</span>
          <div className="relative h-2 flex-1 rounded-full" style={{ background: "var(--surface-inset)" }}>
            <div className="absolute h-full rounded-full" style={{ width: `${(Math.abs(r.pnl) / max) * 100}%`, background: r.pnl >= 0 ? "var(--long)" : "var(--short)" }} />
          </div>
          <span className={"mono w-20 text-right " + pnlClass(r.pnl)}>{fmtINR(r.pnl)}</span>
          <span className="mono w-10 text-right text-text-faint">{r.trades}</span>
        </div>
      ))}
    </div>
  );
}
function Hist({ data, labelKey }: { data: any[]; labelKey: string }) {
  if (!data || data.length === 0) return <span className="text-dense text-text-faint">no data</span>;
  const max = Math.max(1, ...data.map((d) => d.count));
  return (
    <div className="flex items-end gap-1" style={{ height: 90 }}>
      {data.map((d, i) => (
        <div key={i} className="flex flex-1 flex-col items-center justify-end gap-1">
          <div className="w-full rounded-t" style={{ height: `${(d.count / max) * 70}px`, background: "var(--brand)" }} title={`${d.count}`} />
          <span className="text-micro text-text-faint">{String(d[labelKey])}</span>
        </div>
      ))}
    </div>
  );
}

export function Analytics() {
  const stale = useStore((s) => s.connection) !== "open";
  const [period, setPeriod] = useState<"today" | "7d" | "30d" | "all">("all");
  const { data: a } = useQuery({ queryKey: ["analytics", period], queryFn: () => api.analytics(period), refetchInterval: 12000 });
  const k = a?.kpis;
  const hoursMax = Math.max(1, ...(a?.hour_heatmap ?? []).map((h: any) => Math.abs(h.pnl)));
  const wdMax = Math.max(1, ...(a?.weekday_heatmap ?? []).map((h: any) => Math.abs(h.pnl)));

  return (
    <div className={"flex h-full flex-col " + (stale ? "stale" : "")}>
      <div className="flex items-center gap-2 border-b px-3 py-1.5">
        <span className="eyebrow">Analytics</span>
        <span className="rounded-chip px-2 py-0.5 text-micro" style={{ background: a?.dataset === "live" ? "color-mix(in srgb, var(--mode-live) 16%, transparent)" : "color-mix(in srgb, var(--mode-sim) 16%, transparent)", color: a?.dataset === "live" ? "var(--mode-live)" : "var(--mode-sim)" }}>{(a?.dataset ?? "sim").toUpperCase()} dataset</span>
        <div className="flex-1" />
        {(["today", "7d", "30d", "all"] as const).map((pp) => (
          <button key={pp} onClick={() => setPeriod(pp)} className={"rounded-control border px-1.5 py-0.5 text-micro " + (period === pp ? "text-text-hi" : "text-text-lo")} style={period === pp ? { borderColor: "var(--brand)" } : undefined}>{pp}</button>
        ))}
      </div>
      <div className="grid flex-1 gap-3 overflow-auto p-3" style={{ gridTemplateColumns: "repeat(12,minmax(0,1fr))", gridAutoRows: "min-content" }}>
        <P title="KPIs" span={12}>
          <div className="grid grid-cols-5 gap-x-4 gap-y-3">
            <K label="trades" value={k?.trades ?? 0} />
            <K label="win rate" value={fmtPct(k?.win_rate, 0, false)} />
            <K label="profit factor" value={fmtNum(k?.profit_factor, 2)} />
            <K label="expectancy" value={fmtNum(k?.expectancy_R, 3) + "R"} cls={pnlClass(k?.expectancy_R)} />
            <K label="sharpe-like" value={fmtNum(k?.sharpe, 2)} />
            <K label="avg win" value={fmtNum(k?.avg_win_R, 2) + "R"} cls="text-long" />
            <K label="avg loss" value={fmtNum(k?.avg_loss_R, 2) + "R"} cls="text-short" />
            <K label="largest win" value={fmtINR(k?.largest_win)} cls="text-long" />
            <K label="largest loss" value={fmtINR(k?.largest_loss)} cls="text-short" />
            <K label="max drawdown" value={fmtINR(k?.max_dd)} cls="text-short" />
          </div>
        </P>
        <P title="Equity curve" span={6}><EquityChart data={a?.equity_curve ?? []} height={140} /></P>
        <P title="Drawdown curve" span={6}><EquityChart data={a?.drawdown_curve ?? []} height={140} /></P>
        <P title="By sleeve" span={6}><Breakdown rows={a?.by_sleeve ?? []} /></P>
        <P title="By setup" span={6}><Breakdown rows={a?.by_setup ?? []} /></P>
        <P title="By instrument" span={6}><Breakdown rows={a?.by_instrument ?? []} /></P>
        <P title="By side" span={6}><Breakdown rows={a?.by_side ?? []} /></P>
        <P title="R-multiple distribution" span={6}><Hist data={a?.r_histogram ?? []} labelKey="bucket" /></P>
        <P title="Hold-time distribution" span={6}><Hist data={a?.holdtime_histogram ?? []} labelKey="bucket" /></P>
        <P title="By hour-of-day" span={6}>
          <div className="flex flex-wrap gap-1">
            {(a?.hour_heatmap ?? []).length === 0 ? <span className="text-dense text-text-faint">no trades</span>
              : a.hour_heatmap.map((h: any) => <HeatCell key={h.hour} value={`${h.hour}h`} norm={h.pnl / hoursMax} className="text-micro" />)}
          </div>
        </P>
        <P title="By weekday" span={6}>
          <div className="flex flex-wrap gap-1">
            {(a?.weekday_heatmap ?? []).length === 0 ? <span className="text-dense text-text-faint">no trades</span>
              : a.weekday_heatmap.map((h: any) => <HeatCell key={h.day} value={h.day} norm={h.pnl / wdMax} className="text-micro" />)}
          </div>
        </P>
      </div>
    </div>
  );
}

// F&O research on the curated data lake (Pillars 1-5): lake coverage, per-day
// option analytics, and an on-demand backtest of fno_signals over fno_backtest.
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api } from "@/lib/api";

const num = (v: any, dp = 2) =>
  v == null || Number.isNaN(Number(v))
    ? "—"
    : Number(v).toLocaleString("en-IN", { maximumFractionDigits: dp });

function Panel({ title, span = 12, children }: { title: string; span?: number; children: ReactNode }) {
  return (
    <div className="flex min-h-0 flex-col rounded-panel border bg-surface" style={{ gridColumn: `span ${span}` }}>
      <div className="border-b px-3 py-1.5 eyebrow">{title}</div>
      <div className="min-h-0 flex-1 overflow-auto p-3">{children}</div>
    </div>
  );
}

function K({ label, v }: { label: string; v: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="eyebrow">{label}</span>
      <span className="mono text-[15px] text-text-hi">{v}</span>
    </div>
  );
}

export function FnoResearch() {
  const [underlying, setUnderlying] = useState("NIFTY");
  const [start, setStart] = useState("2026-01-01");

  const lake = useQuery({ queryKey: ["fno-lake", start], queryFn: () => api.fnoLake(start), refetchInterval: 60000 });
  const analytics = useQuery({
    queryKey: ["fno-analytics", underlying, start],
    queryFn: () => api.fnoAnalytics(underlying, start),
    refetchInterval: 60000,
  });
  const bt = useQuery({
    queryKey: ["fno-backtest", underlying, start],
    queryFn: () => api.fnoBacktest(underlying, start),
    enabled: false, // on-demand: a backtest is heavy, so only run it on click
  });

  const rows: any[] = analytics.data?.analytics ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b px-3 py-1.5">
        <span className="eyebrow">F&amp;O Research · lake</span>
        <div className="flex-1" />
        <label className="eyebrow">underlying</label>
        <input
          value={underlying}
          onChange={(e) => setUnderlying(e.target.value.toUpperCase())}
          className="w-28 rounded-control border bg-surface-inset px-2 py-1 mono text-dense outline-none"
        />
        <label className="eyebrow ml-2">from</label>
        <input
          type="date"
          value={start}
          onChange={(e) => setStart(e.target.value)}
          className="rounded-control border bg-surface-inset px-2 py-1 mono text-dense outline-none"
        />
      </div>

      <div
        className="grid flex-1 gap-3 overflow-auto p-3"
        style={{ gridTemplateColumns: "repeat(12,minmax(0,1fr))", gridAutoRows: "min-content" }}
      >
        <Panel title="Lake coverage" span={12}>
          <table className="w-full text-dense">
            <thead className="text-text-lo">
              <tr>
                <th className="px-1 py-0.5 text-left eyebrow">underlying</th>
                <th className="px-1 py-0.5 text-right eyebrow">rows</th>
                <th className="px-1 py-0.5 text-right eyebrow">days</th>
                <th className="px-1 py-0.5 text-right eyebrow">fut</th>
                <th className="px-1 py-0.5 text-right eyebrow">opt</th>
                <th className="px-1 py-0.5 text-right eyebrow">first</th>
                <th className="px-1 py-0.5 text-right eyebrow">last</th>
              </tr>
            </thead>
            <tbody>
              {(lake.data?.underlyings ?? []).map((u: any) => (
                <tr key={u.underlying} className="border-b border-line">
                  <td className="px-1 py-0.5 text-text-hi">{u.underlying}</td>
                  <td className="px-1 py-0.5 text-right mono">{num(u.rows, 0)}</td>
                  <td className="px-1 py-0.5 text-right mono">{u.days}</td>
                  <td className="px-1 py-0.5 text-right mono">{u.fut}</td>
                  <td className="px-1 py-0.5 text-right mono">{u.opt}</td>
                  <td className="px-1 py-0.5 text-right mono text-text-faint">{String(u.first ?? "").slice(0, 10)}</td>
                  <td className="px-1 py-0.5 text-right mono text-text-faint">{String(u.last ?? "").slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel
          title={
            `Option analytics · ${underlying}` +
            (analytics.data?.underlying_last_close ? ` · last ${num(analytics.data.underlying_last_close, 1)}` : "")
          }
          span={12}
        >
          <table className="w-full text-dense">
            <thead className="text-text-lo">
              <tr>
                <th className="px-1 py-0.5 text-left eyebrow">date</th>
                <th className="px-1 py-0.5 text-right eyebrow">PCR(OI)</th>
                <th className="px-1 py-0.5 text-right eyebrow">ATM IV</th>
                <th className="px-1 py-0.5 text-right eyebrow">net GEX</th>
                <th className="px-1 py-0.5 text-right eyebrow">max pain</th>
                <th className="px-1 py-0.5 text-right eyebrow">skew</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(-15).map((r: any) => (
                <tr key={r.trade_date} className="border-b border-line">
                  <td className="px-1 py-0.5 mono text-text-faint">{String(r.trade_date).slice(0, 10)}</td>
                  <td className="px-1 py-0.5 text-right mono">{num(r.pcr_oi)}</td>
                  <td className="px-1 py-0.5 text-right mono">{num(r.atm_iv, 3)}</td>
                  <td className="px-1 py-0.5 text-right mono">{num(r.net_gex, 0)}</td>
                  <td className="px-1 py-0.5 text-right mono">{num(r.max_pain, 0)}</td>
                  <td className="px-1 py-0.5 text-right mono">{num(r.skew, 3)}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-1 py-2 text-text-faint">
                    No data for {underlying} in range.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Panel>

        <Panel title="Backtest · fno_signals over the lake" span={12}>
          <div className="mb-2 flex items-center gap-2">
            <button
              onClick={() => bt.refetch()}
              disabled={bt.isFetching}
              className="rounded-control border px-2 py-1 text-dense disabled:opacity-40"
              style={{ background: "var(--brand)", color: "var(--ink)" }}
            >
              {bt.isFetching ? "running…" : "Run backtest"}
            </button>
            <span className="text-micro text-text-faint">
              defined-risk only · bias-audited · needs ~20+ lake days for signals
            </span>
          </div>
          {bt.data && !bt.data.error ? (
            <div className="grid grid-cols-6 gap-4 text-dense">
              <K label="trades" v={bt.data.n_trades ?? 0} />
              <K label="net P&L" v={"Rs " + num(bt.data.net_pnl, 0)} />
              <K label="win %" v={num(bt.data.win_rate_pct, 1)} />
              <K label="max DD %" v={num(bt.data.max_drawdown_pct, 2)} />
              <K label="lot" v={bt.data.lot_size ?? "—"} />
              <K label="accepted" v={bt.data.signals_accepted ?? 0} />
            </div>
          ) : bt.data?.error ? (
            <span className="text-dense text-warn">{bt.data.error}</span>
          ) : (
            <span className="text-dense text-text-faint">Run a backtest to see results.</span>
          )}
        </Panel>
      </div>
    </div>
  );
}

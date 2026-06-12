// Research / Backtest (Phase 1) — run the intraday pipeline over history and read the
// result: KPIs, equity curve, trade list. Same gate/risk/cost code as live, so the
// numbers are an honest forward estimate, not a separate model.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { EquityChart } from "@/components/charts/EquityChart";
import { fmtINR, fmtNum, fmtTimeIST, pnlClass } from "@/lib/format";
import { useStore } from "@/store/store";

function KPI({ label, value, cls }: { label: string; value: React.ReactNode; cls?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="eyebrow">{label}</span>
      <span className={"mono text-[15px] " + (cls ?? "text-text-hi")}>{value}</span>
    </div>
  );
}

function RunDetail({ id }: { id: number }) {
  const { data } = useQuery({
    queryKey: ["backtest", id],
    queryFn: () => api.backtestRun(id),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 2000 : false),
  });
  if (!data) return <div className="p-4 text-dense text-text-faint">Loading…</div>;
  if (data.status === "running") return <div className="p-6 text-center text-dense text-text-lo">Running backtest…</div>;
  if (data.status === "error") return <div className="p-6 text-center text-dense text-short">Error: {data.error}</div>;
  const m = data.metrics ?? {};
  const trades = data.trades ?? [];
  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-ui text-text-hi">{(data.symbols ?? []).join(", ")}</span>
        <span className="eyebrow">{data.sleeve}</span>
        <span className="mono text-micro text-text-faint">{data.from} → {data.to}</span>
      </div>
      <div className="grid grid-cols-4 gap-x-4 gap-y-3 rounded-panel border bg-surface p-3 md:grid-cols-8">
        <KPI label="trades" value={m.trades ?? 0} />
        <KPI label="net P&L" value={fmtINR(m.net_pnl)} cls={pnlClass(m.net_pnl)} />
        <KPI label="return" value={fmtNum(m.return_pct, 2) + "%"} cls={pnlClass(m.return_pct)} />
        <KPI label="win rate" value={fmtNum(m.win_rate, 1) + "%"} />
        <KPI label="expectancy" value={fmtNum(m.expectancy_R, 3) + "R"} cls={pnlClass(m.expectancy_R)} />
        <KPI label="profit factor" value={fmtNum(m.profit_factor, 2)} />
        <KPI label="max DD" value={fmtINR(m.max_dd)} cls="text-short" />
        <KPI label="sharpe" value={fmtNum(m.sharpe, 2)} />
      </div>
      <div className="rounded-panel border bg-surface p-3">
        <div className="mb-1 eyebrow">Equity curve</div>
        <EquityChart data={m.equity_curve ?? []} height={140} />
      </div>
      <div className="rounded-panel border bg-surface">
        <div className="border-b px-3 py-1.5 eyebrow">Trades · {trades.length}</div>
        <div className="max-h-80 overflow-auto">
          {trades.length === 0 ? (
            <div className="py-6 text-center text-dense text-text-faint">No trades in this window.</div>
          ) : (
            <table className="w-full text-dense">
              <thead className="sticky top-0 bg-surface-raised text-text-lo">
                <tr>{["time", "symbol", "setup", "side", "entry", "exit", "qty", "P&L", "R", "reason"].map((h) => (
                  <th key={h} className="px-2 py-1 text-left eyebrow">{h}</th>))}</tr>
              </thead>
              <tbody>
                {trades.map((t: any, i: number) => (
                  <tr key={i} className="border-b border-line">
                    <td className="px-2 py-1 mono text-micro text-text-faint">{fmtTimeIST(t.ts)}</td>
                    <td className="px-2 py-1 text-text-hi">{t.symbol}</td>
                    <td className="px-2 py-1 text-text-lo">{t.setup}</td>
                    <td className="px-2 py-1" style={{ color: t.side === "BUY" ? "var(--long)" : "var(--short)" }}>{t.side}</td>
                    <td className="px-2 py-1 mono">{fmtNum(t.entry, 1)}</td>
                    <td className="px-2 py-1 mono">{fmtNum(t.exit, 1)}</td>
                    <td className="px-2 py-1 mono">{t.qty}</td>
                    <td className={"px-2 py-1 mono " + pnlClass(t.pnl)}>{fmtINR(t.pnl)}</td>
                    <td className={"px-2 py-1 mono " + pnlClass(t.r_multiple)}>{fmtNum(t.r_multiple, 2)}</td>
                    <td className="px-2 py-1 text-micro text-text-faint">{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function MetaModelPanel() {
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const ds = useQuery({ queryKey: ["research-dataset"], queryFn: api.researchDataset, refetchInterval: 30000 });
  const research = useQuery({ queryKey: ["research"], queryFn: api.research, refetchInterval: 30000 });
  const disc = useQuery({ queryKey: ["research-disc"], queryFn: api.researchDiscrimination, refetchInterval: 30000 });
  const train = useMutation({
    mutationFn: () => api.trainMeta(),
    onSuccess: (r: any) => { toast(`Meta-model trained · held-out ${Math.round((r.metrics?.accuracy ?? 0) * 100)}%`, "info"); qc.invalidateQueries({ queryKey: ["research"] }); },
    onError: (e: any) => toast(String(e.message), "short"),
  });
  const active = research.data?.active;
  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex items-center gap-2">
        <span className="font-ui text-text-hi">Meta-label model</span>
        <span className="text-micro text-text-faint">filters signals by learned win-probability · opt-in</span>
        <span className="flex-1" />
        <button onClick={() => train.mutate()} disabled={train.isPending}
          className="rounded-control px-2 py-1 text-dense font-medium disabled:opacity-40" style={{ background: "var(--brand)", color: "var(--ink)" }}>
          {train.isPending ? "training…" : "Train on history"}
        </button>
      </div>
      <div className="grid grid-cols-3 gap-3 rounded-panel border bg-surface p-3 text-dense">
        <div><span className="eyebrow">labelled trades</span><div className="mono text-[15px]">{ds.data?.n_samples ?? "—"}</div></div>
        <div><span className="eyebrow">base win-rate</span><div className="mono text-[15px]">{ds.data ? Math.round(ds.data.base_rate * 100) + "%" : "—"}</div></div>
        <div><span className="eyebrow">active model</span><div className="mono text-[15px]">{active ? `${Math.round((active.metrics?.accuracy ?? 0) * 100)}% acc` : "none"}</div></div>
      </div>
      {active?.importance?.length > 0 && (
        <div className="rounded-panel border bg-surface p-3">
          <div className="mb-1 eyebrow">Feature importance (active model)</div>
          <div className="flex flex-col gap-0.5">
            {active.importance.map((f: any) => (
              <div key={f.feature} className="flex items-center gap-2 text-dense">
                <span className="w-32 truncate text-text-lo">{f.feature}</span>
                <div className="h-2 flex-1 overflow-hidden rounded-full" style={{ background: "var(--surface-inset)" }}>
                  <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.abs(f.weight) * 40)}%`, background: f.weight >= 0 ? "var(--long)" : "var(--short)" }} />
                </div>
                <span className="mono w-12 text-right">{f.weight >= 0 ? "+" : ""}{f.weight}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="rounded-panel border bg-surface p-3">
        <div className="mb-1 flex items-center gap-2">
          <span className="eyebrow">Feature discrimination</span>
          <span className="text-micro text-text-faint">does any gate separate winners from losers?</span>
          {disc.data?.verdict && (
            <span className="rounded-chip px-1.5 py-0.5 text-micro" style={{
              color: disc.data.verdict === "edge_present" ? "var(--long)" : disc.data.verdict === "weak_or_none" ? "var(--short)" : "var(--warn)",
              background: "color-mix(in srgb, currentColor 14%, transparent)",
            }}>{disc.data.verdict.replace(/_/g, " ")}</span>
          )}
        </div>
        {(disc.data?.features ?? []).length === 0 ? (
          <span className="text-micro text-text-faint">not enough data yet</span>
        ) : (
          <table className="w-full text-dense">
            <thead className="text-text-lo"><tr>{["feature", "win% (high)", "win% (low)", "lift"].map((h) => <th key={h} className="px-1 py-0.5 text-left eyebrow">{h}</th>)}</tr></thead>
            <tbody>
              {disc.data.features.slice(0, 8).map((f: any) => (
                <tr key={f.feature} className="border-b border-line">
                  <td className="px-1 py-0.5 text-text-lo">{f.feature}</td>
                  <td className="px-1 py-0.5 mono">{Math.round(f.win_rate_high * 100)}%</td>
                  <td className="px-1 py-0.5 mono">{Math.round(f.win_rate_low * 100)}%</td>
                  <td className="px-1 py-0.5 mono" style={{ color: Math.abs(f.lift) >= 0.15 ? "var(--long)" : "var(--text-faint)" }}>{f.lift >= 0 ? "+" : ""}{f.lift}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="text-micro text-text-faint">Trains a transparent logistic-regression on (gate scores → win/loss). Reports held-out accuracy. Enable it via config (system.meta_label.enabled) only after a feature shows real lift AND it beats the base rate out-of-sample.</div>
    </div>
  );
}

export function Backtest() {
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const [symbols, setSymbols] = useState("NSE:RELIANCE, NSE:TCS");
  const [fromD, setFromD] = useState("2024-01-01");
  const [toD, setToD] = useState("2024-03-31");
  const [risk, setRisk] = useState(1.0);
  const [selected, setSelected] = useState<number | null>(null);

  const runs = useQuery({ queryKey: ["backtests"], queryFn: api.backtests, refetchInterval: 4000 });
  const start = useMutation({
    mutationFn: () =>
      api.startBacktest({
        symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
        from_date: fromD, to_date: toD, per_trade_pct: risk,
      }),
    onSuccess: (r: any) => { toast(`Backtest #${r.id} started`, "info"); setSelected(r.id); qc.invalidateQueries({ queryKey: ["backtests"] }); },
    onError: (e: any) => toast(String(e.message), "short"),
  });

  return (
    <div className="flex h-full min-h-0">
      <div className="flex w-80 shrink-0 flex-col border-r">
        <div className="border-b px-3 py-1.5 eyebrow">Research · Backtest</div>
        <div className="flex flex-col gap-2 border-b p-3">
          <label className="eyebrow">symbols (comma-sep)</label>
          <textarea value={symbols} onChange={(e) => setSymbols(e.target.value)} rows={2}
            className="rounded-control border bg-surface-inset px-2 py-1 mono text-dense outline-none" />
          <div className="flex gap-2">
            <div className="flex flex-1 flex-col gap-1">
              <label className="eyebrow">from</label>
              <input type="date" value={fromD} onChange={(e) => setFromD(e.target.value)}
                className="rounded-control border bg-surface-inset px-2 py-1 mono text-dense outline-none" />
            </div>
            <div className="flex flex-1 flex-col gap-1">
              <label className="eyebrow">to</label>
              <input type="date" value={toD} onChange={(e) => setToD(e.target.value)}
                className="rounded-control border bg-surface-inset px-2 py-1 mono text-dense outline-none" />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <label className="eyebrow flex-1">per-trade risk %</label>
            <input type="number" step="0.25" value={risk} onChange={(e) => setRisk(+e.target.value)}
              className="w-20 rounded-control border bg-surface-inset px-2 py-1 mono text-dense outline-none" />
          </div>
          <button onClick={() => start.mutate()} disabled={start.isPending}
            className="rounded-control py-1.5 font-medium disabled:opacity-40" style={{ background: "var(--brand)", color: "var(--ink)" }}>
            {start.isPending ? "starting…" : "Run backtest"}
          </button>
          <div className="text-micro text-text-faint">Intraday sleeve. Needs 5m + daily history backfilled for the symbols.</div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {(runs.data ?? []).map((r: any) => (
            <button key={r.id} onClick={() => setSelected(r.id)}
              className={"flex w-full flex-col gap-0.5 border-b border-line px-3 py-1.5 text-left hover:bg-surface-raised " + (selected === r.id ? "bg-surface-raised" : "")}>
              <div className="flex items-center justify-between text-dense">
                <span className="text-text-hi">#{r.id} · {(r.symbols ?? []).length} sym</span>
                <span className={"eyebrow " + (r.status === "done" ? "text-long" : r.status === "error" ? "text-short" : "text-warn")}>{r.status}</span>
              </div>
              <div className="flex items-center justify-between text-micro text-text-faint">
                <span>{r.from} → {r.to}</span>
                {r.net_pnl != null && <span className={"mono " + pnlClass(r.net_pnl)}>{fmtINR(r.net_pnl)}</span>}
              </div>
            </button>
          ))}
        </div>
      </div>
      <div className="min-w-0 flex-1 overflow-auto">
        {selected ? <RunDetail id={selected} /> : <MetaModelPanel />}
      </div>
    </div>
  );
}

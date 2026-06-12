// Risk (frontend_v2 §4.8) — the risk-officer screen: portfolio heat, contributing-R,
// correlation matrix + clusters, exposure, margin, leverage band, drawdown + ks history.
import { useQuery } from "@tanstack/react-query";
import { Fragment, type ReactNode } from "react";
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

function Bar({ value, max, color }: { value: number; max: number; color: string }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full" style={{ background: "var(--surface-inset)" }}>
      <div className="h-full rounded-full" style={{ width: `${max ? Math.min(100, (value / max) * 100) : 0}%`, background: color }} />
    </div>
  );
}

export function Risk() {
  const stale = useStore((s) => s.connection) !== "open";
  const { data: d } = useQuery({ queryKey: ["risk"], queryFn: api.risk, refetchInterval: 8000 });
  const { data: pos } = useQuery({ queryKey: ["positions"], queryFn: api.positions, refetchInterval: 6000 });
  const heatPct = d?.heat_pct ?? 0;
  const lev = d?.leverage_x ?? 0;
  const cm = d?.correlation_matrix ?? { instruments: [], matrix: [] };
  const contrib = [...(pos ?? [])].sort((a, b) => b.R_at_risk - a.R_at_risk);
  const expSleeve = Object.entries(d?.exposure?.by_sleeve ?? {});
  const expMax = Math.max(1, ...expSleeve.map(([, v]) => v as number));
  const heatColor = heatPct >= 100 ? "var(--short)" : heatPct >= 75 ? "var(--warn)" : "var(--long)";

  return (
    <div className={"grid h-full gap-3 overflow-auto p-3 " + (stale ? "stale" : "")} style={{ gridTemplateColumns: "repeat(12,minmax(0,1fr))", gridAutoRows: "min-content" }}>
      <P title="Portfolio Heat" span={4}>
        <div className="mb-1 flex items-baseline justify-between">
          <span className="mono text-[20px]">{fmtINR(d?.open_R)}</span>
          <span className="text-dense text-text-lo">/ {fmtINR(d?.portfolio_limit_R)} · {fmtPct(heatPct, 0, false)}</span>
        </div>
        <Bar value={heatPct} max={100} color={heatColor} />
        <div className="mt-2 text-dense text-text-lo">{d?.num_positions ?? 0} / {d?.max_positions ?? 0} positions</div>
      </P>
      <P title="Leverage" span={4}>
        <div className="mb-1 mono text-[20px]" style={{ color: lev > 3 ? "var(--short)" : "var(--text-hi)" }}>{fmtNum(lev, 2)}x</div>
        <Bar value={lev} max={4} color={lev > 3 ? "var(--short)" : lev > 1.5 ? "var(--brand)" : "var(--text-lo)"} />
        <div className="mt-1 text-micro text-text-faint">target band 1.5–3.0x</div>
      </P>
      <P title="Margin" span={4}>
        <div className="flex justify-between text-dense"><span className="text-text-lo">used</span><span className="mono">{fmtINR(d?.margin?.used)}</span></div>
        <div className="flex justify-between text-dense"><span className="text-text-lo">available</span><span className="mono">{fmtINR(d?.margin?.available)}</span></div>
        <div className="mt-1"><Bar value={d?.margin?.used ?? 0} max={(d?.margin?.used ?? 0) + (d?.margin?.available ?? 0) || 1} color="var(--brand)" /></div>
      </P>

      <P title="Contributing R" span={6}>
        {contrib.length === 0 ? <span className="text-dense text-text-faint">No open positions.</span> : (
          <div className="flex flex-col gap-0.5 text-dense">
            {contrib.map((p) => (
              <div key={String(p.id)} className="flex items-center gap-2">
                <span className="w-28 shrink-0 truncate text-text-hi">{p.instrument}</span>
                <span className="eyebrow w-20">{p.sleeve}</span>
                <span className="flex-1"><Bar value={p.R_at_risk} max={Math.max(1, ...contrib.map((x) => x.R_at_risk))} color="var(--warn)" /></span>
                <span className="mono w-20 text-right">{fmtINR(p.R_at_risk)}</span>
                <span className={"mono w-12 text-right " + pnlClass(p.R_multiple)}>{fmtNum(p.R_multiple, 1)}R</span>
              </div>
            ))}
          </div>
        )}
      </P>

      <P title="Exposure by sleeve" span={6}>
        {expSleeve.length === 0 ? <span className="text-dense text-text-faint">No exposure.</span> : (
          <div className="flex flex-col gap-1 text-dense">
            {expSleeve.map(([k, v]) => (
              <div key={k} className="flex items-center gap-2">
                <span className="w-28 shrink-0 text-text-lo">{k}</span>
                <span className="flex-1"><Bar value={v as number} max={expMax} color="var(--info)" /></span>
                <span className="mono w-24 text-right">{fmtINR(v as number)}</span>
              </div>
            ))}
            <div className="mt-1 flex gap-4 text-micro text-text-faint">
              <span>long <span className="mono text-long">{fmtINR(d?.exposure?.by_side?.long)}</span></span>
              <span>short <span className="mono text-short">{fmtINR(d?.exposure?.by_side?.short)}</span></span>
            </div>
          </div>
        )}
      </P>

      <P title="Correlation Matrix" span={6}>
        {cm.instruments.length < 2 ? <span className="text-dense text-text-faint">Needs ≥2 open positions to correlate.</span> : (
          <>
            <div className="overflow-auto">
              <div className="inline-grid gap-0.5" style={{ gridTemplateColumns: `64px repeat(${cm.instruments.length}, 40px)` }}>
                <div />
                {cm.instruments.map((s: string) => <div key={s} className="eyebrow truncate text-center">{s.slice(0, 5)}</div>)}
                {cm.matrix.map((row: number[], i: number) => (
                  <Fragment key={i}>
                    <div className="eyebrow truncate">{cm.instruments[i].slice(0, 6)}</div>
                    {row.map((v, j) => <HeatCell key={i + "-" + j} value={fmtNum(v, 1)} norm={v} className="text-center text-micro" />)}
                  </Fragment>
                ))}
              </div>
            </div>
            {(d?.clusters ?? []).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {d.clusters.map((c: string[], i: number) => (
                  <span key={i} className="rounded-chip px-1.5 py-0.5 text-micro" style={{ background: "color-mix(in srgb, var(--warn) 16%, transparent)", color: "var(--warn)" }}>⚠ {c.join(" · ")}</span>
                ))}
              </div>
            )}
          </>
        )}
      </P>

      <P title="Drawdown · today" span={6}>
        <EquityChart data={(d?.drawdown_curve ?? []) as any} height={120} />
        <div className="mt-2">
          <span className="eyebrow">Kill-switch trips</span>
          {(d?.killswitch_history ?? []).length === 0 ? <span className="ml-2 text-dense text-text-faint">none</span> : (
            <div className="mt-1 flex flex-col gap-0.5 text-dense">
              {d.killswitch_history.map((h: any, i: number) => (
                <div key={i} className="flex justify-between"><span className="text-text-lo">{h.date}</span><span className="mono text-short">{fmtINR(h.day_pnl)}</span></div>
              ))}
            </div>
          )}
        </div>
      </P>
    </div>
  );
}

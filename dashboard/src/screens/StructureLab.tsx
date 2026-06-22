// §10 Phase 6 — Structure Lab: pick an options structure and see its expiry payoff,
// net Greeks, scenario/stress VaR, SPAN margin, and expiry verdict (all from the
// backend Phase 5 engines). Paper analysis tool — places no orders.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Leg = { opt: string; strike: number; side: string; lots: number };

const STEP = 50; // round strikes to a 50-pt grid (index options)
const r50 = (x: number) => Math.round(x / STEP) * STEP;

const PRESETS: Record<string, (s: number) => Leg[]> = {
  "Bull call spread": (s) => [
    { opt: "CE", strike: r50(s), side: "BUY", lots: 1 },
    { opt: "CE", strike: r50(s * 1.02), side: "SELL", lots: 1 },
  ],
  "Bear put spread": (s) => [
    { opt: "PE", strike: r50(s), side: "BUY", lots: 1 },
    { opt: "PE", strike: r50(s * 0.98), side: "SELL", lots: 1 },
  ],
  "Short straddle": (s) => [
    { opt: "CE", strike: r50(s), side: "SELL", lots: 1 },
    { opt: "PE", strike: r50(s), side: "SELL", lots: 1 },
  ],
  "Iron condor": (s) => [
    { opt: "PE", strike: r50(s * 0.96), side: "BUY", lots: 1 },
    { opt: "PE", strike: r50(s * 0.98), side: "SELL", lots: 1 },
    { opt: "CE", strike: r50(s * 1.02), side: "SELL", lots: 1 },
    { opt: "CE", strike: r50(s * 1.04), side: "BUY", lots: 1 },
  ],
};

function PayoffChart({ curve, breakevens, spot }: { curve: any[]; breakevens: number[]; spot: number }) {
  if (!curve || curve.length < 2) return null;
  const W = 600, H = 220, pad = 28;
  const spots = curve.map((p) => p.spot);
  const pnls = curve.map((p) => p.pnl);
  const sMin = Math.min(...spots), sMax = Math.max(...spots);
  const pMin = Math.min(...pnls, 0), pMax = Math.max(...pnls, 0);
  const x = (s: number) => pad + ((s - sMin) / (sMax - sMin || 1)) * (W - 2 * pad);
  const y = (p: number) => pad + ((pMax - p) / (pMax - pMin || 1)) * (H - 2 * pad);
  const pts = curve.map((p) => `${x(p.spot).toFixed(1)},${y(p.pnl).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      <line x1={pad} y1={y(0)} x2={W - pad} y2={y(0)} stroke="var(--line)" strokeDasharray="3 3" />
      <line x1={x(spot)} y1={pad} x2={x(spot)} y2={H - pad} stroke="var(--line)" strokeDasharray="1 3" />
      <polyline points={pts} fill="none" stroke="var(--long)" strokeWidth={1.75} />
      {(breakevens || []).map((be, i) => (
        <line key={i} x1={x(be)} y1={pad} x2={x(be)} y2={H - pad} stroke="var(--warn)" strokeDasharray="2 2" />
      ))}
    </svg>
  );
}

export function StructureLab() {
  const [preset, setPreset] = useState<string>("Bull call spread");
  const [spot, setSpot] = useState<number>(20000);
  const [iv, setIv] = useState<number>(0.15);
  const [dte, setDte] = useState<number>(7);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    let live = true;
    const legs = PRESETS[preset](spot);
    api
      .analyzeStructure({ spot, iv, dte, lot_size: 50, legs })
      .then((r) => live && (setRes(r), setErr("")))
      .catch((e) => live && setErr(String(e)));
    return () => {
      live = false;
    };
  }, [preset, spot, iv, dte]);

  const g = res?.net_greeks ?? {};
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b px-3 py-2">
        <span className="eyebrow">Structure Lab</span>
        <span className="text-micro text-text-faint">payoff · greeks · stress-VaR · SPAN — paper only, no orders</span>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2 text-dense">
        {Object.keys(PRESETS).map((p) => (
          <button
            key={p}
            onClick={() => setPreset(p)}
            className="rounded-control border px-2 py-0.5"
            style={{ borderColor: p === preset ? "var(--long)" : "var(--line)", color: p === preset ? "var(--long)" : "var(--text-lo)" }}
          >
            {p}
          </button>
        ))}
        <span className="ml-2">spot <input type="number" value={spot} onChange={(e) => setSpot(+e.target.value || 0)} className="w-24 rounded-control border bg-surface px-1" /></span>
        <span>IV <input type="number" step="0.01" value={iv} onChange={(e) => setIv(+e.target.value || 0)} className="w-16 rounded-control border bg-surface px-1" /></span>
        <span>DTE <input type="number" value={dte} onChange={(e) => setDte(+e.target.value || 0)} className="w-14 rounded-control border bg-surface px-1" /></span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {err && <div className="text-micro" style={{ color: "var(--short)" }}>{err}</div>}
        {res && (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <div className="rounded-panel border bg-surface p-2 lg:col-span-2">
              <div className="eyebrow mb-1">Expiry payoff</div>
              <PayoffChart curve={res.payoff} breakevens={res.breakevens} spot={res.spot} />
              <div className="mt-1 flex gap-4 text-micro text-text-lo">
                <span>max profit <span style={{ color: "var(--long)" }}>{res.max_profit}</span></span>
                <span>max loss <span style={{ color: "var(--short)" }}>{res.max_loss}</span></span>
                <span>breakevens <span className="mono">{(res.breakevens || []).join(", ") || "—"}</span></span>
              </div>
            </div>
            <div className="rounded-panel border bg-surface p-2">
              <div className="eyebrow mb-1">Risk profile</div>
              <table className="w-full text-dense">
                <tbody>
                  {[["delta", g.delta], ["gamma", g.gamma], ["vega", g.vega], ["theta", g.theta]].map(([k, v]) => (
                    <tr key={k as string}><td className="py-0.5 text-text-lo">{k}</td><td className="py-0.5 text-right mono">{v}</td></tr>
                  ))}
                  <tr><td className="py-0.5 text-text-lo">stress-VaR</td><td className="py-0.5 text-right mono" style={{ color: "var(--short)" }}>{res.stress_var}</td></tr>
                  <tr><td className="py-0.5 text-text-lo">SPAN margin</td><td className="py-0.5 text-right mono">{res.span_margin}</td></tr>
                  <tr><td className="py-0.5 text-text-lo">expiry</td><td className="py-0.5 text-right mono">{res.expiry_action}</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

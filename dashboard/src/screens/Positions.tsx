// Positions (frontend_v2 §4.4) — every open position + protective state + live
// analytics, grouped by sleeve with subtotals, F&O leg expansion + net Greeks,
// distance badges, guarded close/modify, portfolio footer.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Pencil } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { HoldButton } from "@/components/HoldButton";
import { RChip, Sparkline } from "@/components/viz";
import { TickNum } from "@/components/TickNum";
import { fmtAge, fmtINR, fmtNum, pnlClass } from "@/lib/format";
import type { Position } from "@/lib/types";
import { useStore } from "@/store/store";

const TEMPLATE = "minmax(130px,1.4fr) 54px 70px 84px 92px 92px 64px 52px 92px 96px 52px 96px";
const HEADS = ["Instrument", "Qty", "Entry", "LTP", "Stop", "Target", "R@risk", "R", "uP&L", "MAE/MFE", "Age", ""];

function dist(ltp: number, level: number) {
  if (!ltp || !level) return null;
  return ((level - ltp) / ltp) * 100;
}
function Lvl({ ltp, level }: { ltp: number; level: number }) {
  const d = dist(ltp, level);
  return (
    <span className="mono">
      {fmtNum(level, 1)}
      {d != null && <span className="ml-1 text-micro text-text-faint">{(d >= 0 ? "+" : "") + d.toFixed(1)}%</span>}
    </span>
  );
}

function PositionRow({ p }: { p: Position }) {
  const toast = useStore((s) => s.toast);
  const openInspector = useStore((s) => s.openInspector);
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [stop, setStop] = useState(p.stop);
  const [target, setTarget] = useState(p.target);
  const isStruct = p.side === "STRUCTURE";
  const long = p.side === "BUY";
  const nearStop = !isStruct && p.stop > 0 && (long ? p.ltp <= p.stop * 1.004 : p.ltp >= p.stop * 0.996);

  const close = useMutation({
    mutationFn: () => api.closePosition(String(p.id)),
    onSuccess: () => { toast(`Close sent · ${p.instrument}`, "warn"); qc.invalidateQueries({ queryKey: ["positions"] }); },
    onError: (e: any) => toast(String(e.message), "short"),
  });
  const modify = useMutation({
    mutationFn: () => api.modifyPosition(String(p.id), stop, target),
    onSuccess: () => { toast(`Modify sent · ${p.instrument}`, "info"); setEditing(false); qc.invalidateQueries({ queryKey: ["positions"] }); },
    onError: (e: any) => toast(String(e.message), "short"),
  });

  return (
    <>
      <div className="grid items-center border-b border-line px-3 text-dense" style={{ gridTemplateColumns: TEMPLATE, minHeight: 30, borderLeft: nearStop ? "2px solid var(--warn)" : "2px solid transparent" }}>
        <div className="flex items-center gap-1 truncate">
          {isStruct && (
            <button onClick={() => setOpen((o) => !o)} className="text-text-faint hover:text-text-hi">
              {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </button>
          )}
          <span style={{ color: long ? "var(--long)" : isStruct ? "var(--info)" : "var(--short)" }}>{long ? "▲" : isStruct ? "◆" : "▼"}</span>
          <button onClick={() => openInspector(isStruct ? "structure" : "position", p)} className="truncate text-text-hi hover:text-brand">{p.instrument}</button>
        </div>
        <div className="text-right mono">{p.qty}</div>
        <div className="text-right mono">{isStruct ? "—" : fmtNum(p.entry, 1)}</div>
        <div className="text-right"><TickNum value={isStruct ? null : p.ltp} fmt={(v) => (v == null ? "—" : fmtNum(v, 1))} className="mono" /></div>
        <div className="text-right">{isStruct ? "—" : <Lvl ltp={p.ltp} level={p.stop} />}</div>
        <div className="text-right">{isStruct ? "—" : <Lvl ltp={p.ltp} level={p.target} />}</div>
        <div className="text-right mono">{fmtINR(p.R_at_risk)}</div>
        <div className="text-right"><RChip r={p.R_multiple} /></div>
        <div className={"text-right mono " + pnlClass(p.unrealized)}><TickNum value={p.unrealized} fmt={(v) => fmtINR(v)} /></div>
        <div className="text-right mono text-micro"><span className="text-short">{fmtINR(p.mae)}</span> / <span className="text-long">{fmtINR(p.mfe)}</span></div>
        <div className="text-right mono text-text-lo">{fmtAge(p.opened_at)}</div>
        <div className="flex items-center justify-end gap-1">
          {!isStruct && <button onClick={() => setEditing((e) => !e)} className="text-text-faint hover:text-text-hi" title="Modify stop/target"><Pencil size={11} /></button>}
          <HoldButton danger label="✕" ms={1500} onConfirm={() => close.mutate()} />
        </div>
      </div>

      {isStruct && open && (
        <div className="border-b border-line bg-surface-inset px-3 py-2 text-dense" style={{ gridColumn: "1 / -1" }}>
          <div className="mb-1 flex gap-4 text-micro text-text-lo">
            <span>net max-loss <span className="mono text-short">{fmtINR(p.structure?.net_max_loss)}</span></span>
            {p.structure?.greeks && (["delta", "theta", "gamma", "vega"] as const).map((g) => (
              <span key={g}>{g[0].toUpperCase()} <span className="mono">{fmtNum(p.structure!.greeks![g], 2)}</span></span>
            ))}
          </div>
          {(p.structure?.legs ?? []).map((leg: any, i: number) => (
            <div key={i} className="flex gap-3 py-0.5 text-micro">
              <span className="w-40 truncate">{leg.instrument}</span>
              <span style={{ color: leg.side === "BUY" ? "var(--long)" : "var(--short)" }}>{leg.side}</span>
              <span className="mono">{leg.qty}</span>
              <span className="mono text-text-lo">@ {fmtNum(leg.entry, 1)}</span>
              <span className="mono">ltp {fmtNum(leg.ltp, 1)}</span>
            </div>
          ))}
        </div>
      )}

      {editing && !isStruct && (
        <div className="flex items-center gap-2 border-b border-line bg-surface-inset px-3 py-2 text-dense" style={{ gridColumn: "1 / -1" }}>
          <span className="eyebrow">stop</span>
          <input type="number" value={stop} onChange={(e) => setStop(+e.target.value)} className="w-24 rounded-control border bg-surface px-1.5 py-0.5 mono outline-none" />
          <span className="eyebrow">target</span>
          <input type="number" value={target} onChange={(e) => setTarget(+e.target.value)} className="w-24 rounded-control border bg-surface px-1.5 py-0.5 mono outline-none" />
          <button onClick={() => modify.mutate()} className="rounded-control border px-2 py-0.5" style={{ borderColor: "var(--brand)" }}>Apply</button>
          <button onClick={() => setEditing(false)} className="text-text-faint">cancel</button>
        </div>
      )}
    </>
  );
}

export function Positions() {
  const stale = useStore((s) => s.connection) !== "open";
  const { data } = useQuery({ queryKey: ["positions"], queryFn: api.positions, refetchInterval: 4000 });
  const rows = data ?? [];
  const groups = Array.from(new Set(rows.map((r) => r.sleeve)));
  const totUnreal = rows.reduce((s, r) => s + r.unrealized, 0);
  const totR = rows.reduce((s, r) => s + r.R_at_risk, 0);
  const netGreeks = rows.reduce((acc, r) => {
    const g = r.structure?.greeks;
    if (g) (["delta", "theta", "gamma", "vega"] as const).forEach((k) => (acc[k] += g[k] ?? 0));
    return acc;
  }, { delta: 0, theta: 0, gamma: 0, vega: 0 });

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b px-3 py-1.5"><span className="eyebrow">Positions</span><span className="text-micro text-text-faint">{rows.length} open</span></div>
      <div className="grid border-b bg-surface-raised px-3 text-text-lo" style={{ gridTemplateColumns: TEMPLATE, minHeight: 28 }}>
        {HEADS.map((h, i) => <div key={i} className={"eyebrow self-center " + (i > 0 && i < 11 ? "text-right" : "")}>{h}</div>)}
      </div>
      <div className={"flex-1 overflow-auto " + (stale ? "stale" : "")}>
        {rows.length === 0 ? (
          <div className="py-8 text-center text-dense text-text-faint">No open positions. The engine is scanning for qualifying setups.</div>
        ) : (
          groups.map((g) => {
            const gr = rows.filter((r) => r.sleeve === g);
            const gUnreal = gr.reduce((s, r) => s + r.unrealized, 0);
            const gR = gr.reduce((s, r) => s + r.R_at_risk, 0);
            return (
              <div key={g}>
                <div className="flex items-center justify-between bg-surface-inset px-3 py-1">
                  <span className="eyebrow">{g} · {gr.length}</span>
                  <span className="text-micro text-text-lo">openR <span className="mono">{fmtINR(gR)}</span> · uP&L <span className={"mono " + pnlClass(gUnreal)}>{fmtINR(gUnreal)}</span></span>
                </div>
                {gr.map((p) => <PositionRow key={String(p.id)} p={p} />)}
              </div>
            );
          })
        )}
      </div>
      <div className="flex items-center gap-5 border-t bg-surface-raised px-3 py-1.5 text-dense">
        <span className="eyebrow">Portfolio</span>
        <span>open R <span className="mono">{fmtINR(totR)}</span></span>
        <span>net uP&L <span className={"mono " + pnlClass(totUnreal)}>{fmtINR(totUnreal)}</span></span>
        <span className="text-text-lo">net Greeks Δ<span className="mono">{fmtNum(netGreeks.delta, 1)}</span> Θ<span className="mono">{fmtNum(netGreeks.theta, 1)}</span> Γ<span className="mono">{fmtNum(netGreeks.gamma, 3)}</span> V<span className="mono">{fmtNum(netGreeks.vega, 1)}</span></span>
      </div>
    </div>
  );
}

// Option Chain + Greeks (frontend_v2 §4.6) — the full options picture the F&O pipeline
// reasons over: calls|strike|puts with OI/IV/Δ heat cells, ATM + ITM + suggested-strike
// highlighting, summary band (PCR/Max-Pain/OI/VIX/DTE), IV skew, strike -> eligibility.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Sparkline } from "@/components/viz";
import { fmtNum, fmtPct } from "@/lib/format";
import { useStore } from "@/store/store";

const FNO = ["NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "ITC", "LT"];
const TEMPLATE = "1fr 1fr 60px 70px 84px 70px 60px 1fr 1fr"; // callOI callIV callΔ callLTP STRIKE putLTP putΔ putIV putOI

function eligibility(side: "call" | "put", cell: any): string {
  if (!cell || cell.iv === 0) return "—";
  const d = Math.abs(cell.delta ?? 0);
  if (d >= 0.4 && d <= 0.6) return "debit-spread long-leg (Δ≈0.5)";
  if (d >= 0.15 && d <= 0.3) return "credit short-leg (Δ 0.15-0.30)";
  if (d >= 0.1 && d < 0.15) return "condor wing";
  return d > 0.6 ? "deep ITM" : "far OTM";
}

function OIHeat({ oi, max }: { oi: number; max: number }) {
  if (!oi) return <span className="text-text-faint">—</span>;
  const f = Math.min(1, oi / max);
  return (
    <span className="mono inline-block w-full rounded-chip px-1 text-right"
      style={{ background: `color-mix(in srgb, var(--heat-pos-2) ${Math.round(f * 70)}%, transparent)` }}>
      {fmtNum(oi, 0)}
    </span>
  );
}

export function OptionChain() {
  const stale = useStore((s) => s.connection) !== "open";
  const openInspector = useStore((s) => s.openInspector);
  const [u, setU] = useState("NIFTY");
  const [expiry, setExpiry] = useState<string | undefined>(undefined);
  const { data, isLoading } = useQuery({ queryKey: ["chain", u, expiry], queryFn: () => api.optionchain(u, expiry), refetchInterval: 6000 });

  const strikes = data?.strikes ?? [];
  const maxOI = Math.max(1, ...strikes.flatMap((r: any) => [r.call?.oi ?? 0, r.put?.oi ?? 0]));
  const suggested = new Set<number>(data?.suggested_strikes ?? []);
  const spot = data?.spot ?? 0;

  return (
    <div className="flex h-full flex-col">
      {/* toolbar + summary band */}
      <div className="flex flex-wrap items-center gap-3 border-b px-3 py-1.5">
        <span className="eyebrow">Option Chain</span>
        <select value={u} onChange={(e) => { setU(e.target.value); setExpiry(undefined); }}
          className="rounded-control border bg-surface-raised px-1.5 py-0.5 text-dense outline-none">
          {FNO.map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
        <select value={expiry ?? data?.expiry ?? ""} onChange={(e) => setExpiry(e.target.value)}
          className="rounded-control border bg-surface-raised px-1.5 py-0.5 text-dense outline-none">
          {(data?.expiries ?? []).map((e: string) => <option key={e} value={e}>{e}</option>)}
        </select>
        <span className="h-4 w-px bg-line" />
        <span className="text-dense">spot <span className="mono text-text-hi">{fmtNum(spot, 1)}</span></span>
        <span className="text-dense">DTE <span className="mono">{data?.dte ?? "—"}</span></span>
        <span className="text-dense">PCR <span className="mono">{fmtNum(data?.pcr, 2)}</span></span>
        <span className="text-dense">Max Pain <span className="mono text-warn">{fmtNum(data?.max_pain, 0)}</span></span>
        <span className="text-dense">CE OI <span className="mono">{fmtNum(data?.ce_oi, 0)}</span></span>
        <span className="text-dense">PE OI <span className="mono">{fmtNum(data?.pe_oi, 0)}</span></span>
        <span className="text-dense">VIX rank <span className="mono">{fmtNum(data?.vix_rank, 0)}</span></span>
        {data?.gex && (
          <span className="text-dense" title="net dealer gamma exposure (regime + flip/walls)">
            GEX{" "}
            <span className="mono" style={{ color: data.gex.regime === "positive_gamma" ? "var(--long)" : "var(--short)" }}>
              {data.gex.regime === "positive_gamma" ? "＋γ" : "－γ"}
            </span>
            {data.gex.flip_strike != null && <span className="ml-1 text-micro text-text-faint">flip {fmtNum(data.gex.flip_strike, 0)}</span>}
            {data.gex.call_wall != null && <span className="ml-1 text-micro text-text-faint">wall {fmtNum(data.gex.call_wall, 0)}/{fmtNum(data.gex.put_wall, 0)}</span>}
          </span>
        )}
        <span className="flex items-center gap-1 text-dense">IV skew <Sparkline data={(data?.iv_skew ?? []).map((s: any) => s.iv)} w={70} h={16} /></span>
      </div>

      {/* header */}
      <div className="grid border-b bg-surface-raised px-3 text-text-lo" style={{ gridTemplateColumns: TEMPLATE, minHeight: 26 }}>
        {["OI", "IV", "Δ", "LTP", "STRIKE", "LTP", "Δ", "IV", "OI"].map((h, i) => (
          <div key={i} className={"eyebrow self-center " + (i === 4 ? "text-center" : "text-right")}>{i < 4 ? "C·" + h : i > 4 ? "P·" + h : h}</div>
        ))}
      </div>

      {/* chain */}
      <div className={"flex-1 overflow-auto " + (stale ? "stale" : "")}>
        {data?.error ? (
          <div className="py-8 text-center text-dense text-text-faint">{data.error} — F&O data needs market hours / segment.</div>
        ) : isLoading ? (
          <div className="py-8 text-center text-dense text-text-faint">Loading chain…</div>
        ) : strikes.map((r: any) => {
          const atm = Math.abs(r.strike - (data?.atm ?? 0)) < 1e-6;
          const callITM = r.strike < spot;
          const putITM = r.strike > spot;
          const sug = suggested.has(r.strike);
          const C = r.call, P = r.put;
          return (
            <div key={r.strike} onClick={() => openInspector("strike", { strike: r.strike, call: C, put: P, eligibility: { call: eligibility("call", C), put: eligibility("put", P) } })}
              className="grid cursor-pointer items-center border-b border-line px-3 text-dense hover:bg-surface-raised"
              style={{ gridTemplateColumns: TEMPLATE, minHeight: 24, background: atm ? "color-mix(in srgb, var(--brand) 8%, transparent)" : undefined }}>
              <div className="text-right" style={{ background: callITM ? "color-mix(in srgb, var(--text-faint) 10%, transparent)" : undefined }}><OIHeat oi={C?.oi ?? 0} max={maxOI} /></div>
              <div className="text-right mono" style={{ background: callITM ? "color-mix(in srgb, var(--text-faint) 10%, transparent)" : undefined }}>{C ? fmtPct(C.iv * 100, 1, false) : "—"}</div>
              <div className="text-right mono text-text-lo">{C ? fmtNum(C.delta, 2) : "—"}</div>
              <div className="text-right mono">{C ? fmtNum(C.ltp, 1) : "—"}</div>
              <div className="text-center mono font-medium" style={{ color: sug ? "var(--brand)" : "var(--text-hi)" }}>{fmtNum(r.strike, 0)}{sug && <span className="ml-1 text-micro text-brand">◆</span>}</div>
              <div className="text-right mono">{P ? fmtNum(P.ltp, 1) : "—"}</div>
              <div className="text-right mono text-text-lo">{P ? fmtNum(P.delta, 2) : "—"}</div>
              <div className="text-right mono" style={{ background: putITM ? "color-mix(in srgb, var(--text-faint) 10%, transparent)" : undefined }}>{P ? fmtPct(P.iv * 100, 1, false) : "—"}</div>
              <div className="text-right" style={{ background: putITM ? "color-mix(in srgb, var(--text-faint) 10%, transparent)" : undefined }}><OIHeat oi={P?.oi ?? 0} max={maxOI} /></div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

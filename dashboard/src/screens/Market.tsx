// Market scanner (frontend_v2 §4.2) — every tracked instrument with decision-driving
// metrics. Virtualized (TanStack Virtual), sortable, filterable, saved scans, column
// chooser, sleeve filter; live LTP merged from the WS price stream.
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, Ban, CandlestickChart, Columns3, Search } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { fmtNum, fmtPct, pnlClass } from "@/lib/format";
import { HeatCell, Sparkline } from "@/components/viz";
import { TickNum } from "@/components/TickNum";
import { useStore } from "@/store/store";
import type { MarketRow } from "@/lib/types";

const ROW_H = 30;

const SCANS: Record<string, (r: MarketRow) => boolean> = {
  "RVOL>2 & >VWAP": (r) => (r.rvol ?? 0) > 2 && (r.vwap_dist ?? 0) > 0,
  "IV rank>70": (r) => (r.iv_rank ?? 0) > 70,
  "near ORB": (r) => r.or_state === "above" || r.or_state === "below",
};

interface Col {
  key: string;
  label: string;
  w: string;
  num?: boolean;
  get?: (r: MarketRow) => number | string | null;
  cell: (r: MarketRow, ltp: number | null) => React.ReactNode;
}

function vwapBadge(v: number | null) {
  if (v == null) return <span className="text-text-faint">—</span>;
  const c = v > 0 ? "var(--long)" : v < 0 ? "var(--short)" : "var(--text-lo)";
  return <span className="mono" style={{ color: c }}>{(v >= 0 ? "+" : "") + v.toFixed(2)}%</span>;
}
function orBadge(s: string | null) {
  if (!s) return <span className="text-text-faint">—</span>;
  const c = s === "above" ? "var(--long)" : s === "below" ? "var(--short)" : "var(--text-lo)";
  return <span className="eyebrow" style={{ color: c }}>{s}</span>;
}

export function Market() {
  const nav = useNavigate();
  const ltps = useStore((s) => s.ltps);
  const stale = useStore((s) => s.connection) !== "open";
  const openInspector = useStore((s) => s.openInspector);
  const { data } = useQuery({ queryKey: ["market"], queryFn: api.market, refetchInterval: 5000 });

  const [search, setSearch] = useState("");
  const [scan, setScan] = useState<string | null>(null);
  const [sleeve, setSleeve] = useState<"all" | "intraday_stocks" | "fno" | "index">("all");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "instrument", dir: 1 });
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [chooser, setChooser] = useState(false);

  const liveLtp = (r: MarketRow) => ltps[String(r.token)] ?? r.ltp;

  const cols: Col[] = [
    { key: "instrument", label: "Instrument", w: "minmax(150px,1.4fr)", get: (r) => r.instrument,
      cell: (r) => (
        <div className="flex items-center gap-1.5">
          {r.fno_ban && <Ban size={11} className="text-short" />}
          <span className="truncate text-text-hi">{r.instrument}</span>
          <button onClick={(e) => { e.stopPropagation(); nav(`/charts?i=${encodeURIComponent(r.instrument)}`); }}
            className="text-text-faint hover:text-brand" title="Open chart"><CandlestickChart size={12} /></button>
        </div>
      ) },
    { key: "ltp", label: "LTP", w: "90px", num: true, get: (r) => liveLtp(r),
      cell: (r, ltp) => <TickNum value={ltp} fmt={(v) => fmtNum(v, 1)} className="mono" /> },
    { key: "chg_pct", label: "%Chg", w: "76px", num: true, get: (r) => r.chg_pct,
      cell: (r) => <span className={"mono " + pnlClass(r.chg_pct)}>{fmtPct(r.chg_pct)}</span> },
    { key: "spark", label: "Day", w: "64px", cell: (r) => <Sparkline data={r.spark} w={56} h={16} /> },
    { key: "rvol", label: "RVOL", w: "70px", num: true, get: (r) => r.rvol,
      // 0 / null => no relative volume yet (e.g. market closed): show neutral, not red.
      cell: (r) => !r.rvol ? <span className="text-text-faint">—</span>
        : <HeatCell value={fmtNum(r.rvol, 2)} norm={(r.rvol - 1) / 2} /> },
    { key: "vwap_dist", label: "VWAP±", w: "82px", num: true, get: (r) => r.vwap_dist, cell: (r) => vwapBadge(r.vwap_dist) },
    { key: "or_state", label: "ORB", w: "64px", get: (r) => r.or_state, cell: (r) => orBadge(r.or_state) },
    { key: "vol_vs_avg", label: "Vol×", w: "64px", num: true, get: (r) => r.vol_vs_avg,
      cell: (r) => <span className="mono">{fmtNum(r.vol_vs_avg, 2)}</span> },
    { key: "oi", label: "OI", w: "84px", num: true, get: (r) => r.oi,
      cell: (r) => <span className="mono text-text-lo">{r.oi == null ? "—" : fmtNum(r.oi, 0)}</span> },
    { key: "iv", label: "IV", w: "64px", num: true, get: (r) => r.iv,
      cell: (r) => <span className="mono">{r.iv == null ? "—" : fmtPct(r.iv * 100, 1, false)}</span> },
    { key: "iv_rank", label: "IVR", w: "64px", num: true, get: (r) => r.iv_rank,
      cell: (r) => r.iv_rank == null ? <span className="text-text-faint">—</span>
        : <HeatCell value={fmtNum(r.iv_rank, 0)} norm={(r.iv_rank - 50) / 50} /> },
    { key: "pcr", label: "PCR", w: "60px", num: true, get: (r) => r.pcr,
      cell: (r) => <span className="mono">{r.pcr == null ? "—" : fmtNum(r.pcr, 2)}</span> },
    { key: "signal_state", label: "Signal", w: "minmax(90px,1fr)", get: (r) => r.signal_state,
      cell: (r) => <span className="truncate text-text-lo">{r.signal_state ?? "—"}</span> },
  ];
  const visible = cols.filter((c) => !hidden.has(c.key));
  const template = visible.map((c) => c.w).join(" ");

  const rows = useMemo(() => {
    let r = (data ?? []).slice();
    if (sleeve !== "all") {
      r = r.filter((x) => (sleeve === "index" ? x.sleeves.length === 0 : x.sleeves.includes(sleeve) || (sleeve === "fno" && x.eligible)));
    }
    if (search) r = r.filter((x) => x.instrument.toLowerCase().includes(search.toLowerCase()));
    if (scan) r = r.filter(SCANS[scan]);
    const col = cols.find((c) => c.key === sort.key);
    if (col?.get) {
      r.sort((a, b) => {
        const va = col.get!(a), vb = col.get!(b);
        if (va == null) return 1;
        if (vb == null) return -1;
        return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
      });
    }
    return r;
    // NOTE: `ltps` is intentionally NOT a dep — re-sorting the whole table on every
    // price tick is wasteful; live LTP is overlaid per-cell via liveLtp() at render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, sleeve, search, scan, sort]);

  const parentRef = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({ count: rows.length, getScrollElement: () => parentRef.current, estimateSize: () => ROW_H, overscan: 12 });

  const toggleSort = (key: string) => setSort((s) => (s.key === key ? { key, dir: (s.dir * -1) as 1 | -1 } : { key, dir: 1 }));

  return (
    <div className="flex h-full flex-col">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-1.5">
        <span className="eyebrow">Market</span>
        <div className="flex items-center gap-1 rounded-control border px-2 py-0.5">
          <Search size={12} className="text-text-faint" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="filter…"
            className="w-28 bg-transparent text-dense outline-none placeholder:text-text-faint" />
        </div>
        <div className="flex gap-1">
          {(["all", "intraday_stocks", "fno", "index"] as const).map((s) => (
            <button key={s} onClick={() => setSleeve(s)}
              className={"rounded-control border px-1.5 py-0.5 text-micro " + (sleeve === s ? "text-text-hi" : "text-text-lo")}
              style={sleeve === s ? { borderColor: "var(--brand)" } : undefined}>{s === "intraday_stocks" ? "intraday" : s}</button>
          ))}
        </div>
        <span className="h-4 w-px bg-line" />
        <div className="flex gap-1">
          {Object.keys(SCANS).map((s) => (
            <button key={s} onClick={() => setScan(scan === s ? null : s)}
              className={"rounded-control border px-1.5 py-0.5 text-micro " + (scan === s ? "text-text-hi" : "text-text-lo")}
              style={scan === s ? { borderColor: "var(--brand)" } : undefined}>{s}</button>
          ))}
        </div>
        <div className="flex-1" />
        <div className="relative">
          <button onClick={() => setChooser((c) => !c)} className="flex items-center gap-1 rounded-control border px-2 py-0.5 text-dense text-text-lo">
            <Columns3 size={12} /> columns
          </button>
          {chooser && (
            <div className="absolute right-0 z-20 mt-1 w-44 rounded-panel border bg-surface-raised p-2 shadow-lg">
              {cols.map((c) => (
                <label key={c.key} className="flex items-center gap-2 py-0.5 text-dense">
                  <input type="checkbox" checked={!hidden.has(c.key)} onChange={() => setHidden((h) => {
                    const n = new Set(h); n.has(c.key) ? n.delete(c.key) : n.add(c.key); return n;
                  })} />
                  {c.label}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* header */}
      <div className="grid border-b bg-surface-raised px-3 text-text-lo" style={{ gridTemplateColumns: template, height: ROW_H }}>
        {visible.map((c) => (
          <button key={c.key} onClick={() => c.get && toggleSort(c.key)}
            className={"flex items-center gap-0.5 " + (c.num ? "justify-end" : "")} title={c.label}>
            <span className="eyebrow">{c.label}</span>
            {sort.key === c.key && (sort.dir === 1 ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}
          </button>
        ))}
      </div>

      {/* virtualized body */}
      <div ref={parentRef} className={"flex-1 overflow-auto " + (stale ? "stale" : "")}>
        {rows.length === 0 ? (
          <div className="py-8 text-center text-dense text-text-faint">No instruments match — adjust the filter or scan.</div>
        ) : (
          <div style={{ height: v.getTotalSize(), position: "relative" }}>
            {v.getVirtualItems().map((vi) => {
              const r = rows[vi.index];
              return (
                <div key={r.key} onClick={() => openInspector("instrument", r)}
                  className="grid cursor-pointer items-center border-b border-line px-3 hover:bg-surface-raised"
                  style={{ gridTemplateColumns: template, height: ROW_H, position: "absolute", top: 0, left: 0, right: 0, transform: `translateY(${vi.start}px)` }}>
                  {visible.map((c) => (
                    <div key={c.key} className={"truncate text-dense " + (c.num ? "text-right" : "")}>{c.cell(r, liveLtp(r))}</div>
                  ))}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

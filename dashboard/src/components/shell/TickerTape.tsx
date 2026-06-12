// Ticker tape — auto-scrolling marquee of tracked instruments (LTP, %chg, mini-spark);
// pauses on hover, click opens Charts. Content is duplicated for a seamless loop.
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { fmtNum, fmtPct, pnlClass } from "@/lib/format";
import { Sparkline } from "@/components/viz";
import type { MarketRow } from "@/lib/types";
import { useStore } from "@/store/store";

export function TickerTape() {
  const nav = useNavigate();
  const stale = useStore((s) => s.connection) !== "open";
  const { data } = useQuery({ queryKey: ["market"], queryFn: api.market, refetchInterval: 5000 });
  if (!data || data.length === 0) return null;
  const items = data.slice(0, 22); // indices + majors; the full universe lives on /market

  const Item = (r: MarketRow, suffix: string) => (
    <button key={r.key + suffix} onClick={() => nav(`/charts?i=${encodeURIComponent(r.instrument)}`)}
      className="flex shrink-0 items-center gap-1.5 px-3">
      <span className="eyebrow">{r.instrument}</span>
      <span className="mono">{fmtNum(r.ltp, 1)}</span>
      <span className={"mono " + pnlClass(r.chg_pct)}>{fmtPct(r.chg_pct, 2)}</span>
      <Sparkline data={r.spark} w={40} h={14} />
    </button>
  );

  return (
    <div className={"relative h-7 overflow-hidden border-b bg-surface-inset text-dense " + (stale ? "stale" : "")}>
      <div className="ticker-track flex h-full items-center">
        {items.map((r) => Item(r, "-a"))}
        {items.map((r) => Item(r, "-b"))}
      </div>
    </div>
  );
}

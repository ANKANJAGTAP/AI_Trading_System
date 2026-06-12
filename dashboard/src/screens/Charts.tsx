// Charts (frontend_v2 §4.3) — price analysis with the system's reasoning overlaid.
// Lightweight Charts: candles + volume + VWAP/200-DMA, signal/trade markers (click ->
// Gate Trail in the Inspector), order-book depth, instrument selector, multi-chart grid.
import {
  ColorType, createChart, type IChartApi, type ISeriesApi, type SeriesMarker, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { useStore } from "@/store/store";

const C = {
  bg: "#0E111A", text: "#8A93A6", grid: "#252A38", up: "#34D399", down: "#F87171",
  brand: "#4FD1E0", sma: "#818CF8", vol: "#252A38",
};
// Lightweight-Charts renders timestamps in UTC. Our candles are IST — shift by +5:30
// so the axis/crosshair read IST wall-clock (09:15 open shows as 09:15, not 03:45).
const IST_OFFSET_S = 5.5 * 3600;
const tsUnix = (ts: string) => (Math.floor(new Date(ts).getTime() / 1000) + IST_OFFSET_S) as UTCTimestamp;

function DepthLadder({ depth }: { depth?: { bids: any[]; asks: any[]; imbalance?: any } }) {
  const bids = depth?.bids ?? [];
  const asks = depth?.asks ?? [];
  const imb = depth?.imbalance;
  const max = Math.max(1, ...bids.map((b) => b.quantity || 0), ...asks.map((a) => a.quantity || 0));
  const Row = ({ d, side }: { d: any; side: "bid" | "ask" }) => (
    <div className="relative flex items-center justify-between px-1.5 text-micro">
      <div className="absolute inset-y-0 right-0" style={{
        width: `${((d.quantity || 0) / max) * 100}%`,
        background: side === "bid" ? "color-mix(in srgb, var(--long) 16%, transparent)" : "color-mix(in srgb, var(--short) 16%, transparent)",
      }} />
      <span className={"mono relative " + (side === "bid" ? "text-long" : "text-short")}>{fmtNum(d.price, 1)}</span>
      <span className="mono relative text-text-lo">{fmtNum(d.quantity, 0)}</span>
    </div>
  );
  if (!bids.length && !asks.length) return <div className="p-2 text-micro text-text-faint">No depth.</div>;
  const imbColor = imb?.bias === "buy" ? "var(--long)" : imb?.bias === "sell" ? "var(--short)" : "var(--text-lo)";
  return (
    <div className="flex flex-col gap-0.5 py-1">
      {asks.slice(0, 5).reverse().map((a, i) => <Row key={"a" + i} d={a} side="ask" />)}
      <div className="my-0.5 h-px bg-line" />
      {bids.slice(0, 5).map((b, i) => <Row key={"b" + i} d={b} side="bid" />)}
      {imb && (
        <div className="mt-1 flex items-center justify-between border-t px-1.5 pt-1 text-micro">
          <span className="eyebrow">imbalance</span>
          <span className="mono" style={{ color: imbColor }}>{(imb.imbalance >= 0 ? "+" : "") + (imb.imbalance * 100).toFixed(0)}% {imb.bias}</span>
        </div>
      )}
    </div>
  );
}

function ChartPanel({ instrument, instruments }: { instrument: string; instruments: string[] }) {
  const [params, setParams] = useSearchParams();
  const openInspector = useStore((s) => s.openInspector);
  const [tf, setTf] = useState("5m");
  const { data } = useQuery({ queryKey: ["chart", instrument, tf], queryFn: () => api.chart(instrument, tf), refetchInterval: 6000 });
  const elRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const series = useRef<{
    candle?: ISeriesApi<"Candlestick">; vol?: ISeriesApi<"Histogram">; vwap?: ISeriesApi<"Line">;
    sma?: ISeriesApi<"Line">; bbU?: ISeriesApi<"Line">; bbL?: ISeriesApi<"Line">; st?: ISeriesApi<"Line">;
  }>({});
  const markerMap = useRef<Map<number, any>>(new Map());
  const priceLines = useRef<any[]>([]);

  useEffect(() => {
    if (!elRef.current) return;
    const chart = createChart(elRef.current, {
      width: elRef.current.clientWidth, height: elRef.current.clientHeight,
      layout: { background: { type: ColorType.Solid, color: C.bg }, textColor: C.text, fontSize: 11 },
      grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
      timeScale: { borderColor: C.grid, timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: C.grid },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;
    series.current.candle = chart.addCandlestickSeries({ upColor: C.up, downColor: C.down, wickUpColor: C.up, wickDownColor: C.down, borderVisible: false });
    series.current.vol = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" } });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    series.current.vwap = chart.addLineSeries({ color: C.brand, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    series.current.sma = chart.addLineSeries({ color: C.sma, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const bbOpts = { color: "#3B4252", lineWidth: 1 as const, priceLineVisible: false, lastValueVisible: false };
    series.current.bbU = chart.addLineSeries(bbOpts);
    series.current.bbL = chart.addLineSeries(bbOpts);
    series.current.st = chart.addLineSeries({ color: "#F0A35E", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });

    const onClick = async (param: any) => {
      if (!param?.time) return;
      const m = markerMap.current.get(Number(param.time));
      if (m?.correlation_id) {
        try {
          openInspector("signal", await api.reconstruct(m.correlation_id));
        } catch {
          openInspector("signal", m);
        }
      }
    };
    chart.subscribeClick(onClick);
    const ro = new ResizeObserver(() => {
      if (elRef.current) chart.applyOptions({ width: elRef.current.clientWidth, height: elRef.current.clientHeight });
    });
    ro.observe(elRef.current);
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; };
  }, [openInspector]);

  useEffect(() => {
    const s = series.current;
    if (!data?.candles || !s.candle) return;
    s.candle.setData(data.candles.map((c: any) => ({ time: tsUnix(c.ts), open: c.open, high: c.high, low: c.low, close: c.close })));
    s.vol?.setData(data.candles.map((c: any) => ({ time: tsUnix(c.ts), value: c.volume, color: c.close >= c.open ? "rgba(52,211,153,.4)" : "rgba(248,113,113,.4)" })));
    s.vwap?.setData((data.overlays?.vwap ?? []).map((p: any) => ({ time: tsUnix(p.ts), value: p.value })));
    s.sma?.setData((data.overlays?.sma200 ?? []).map((p: any) => ({ time: tsUnix(p.ts), value: p.value })));
    s.bbU?.setData((data.overlays?.bb_upper ?? []).map((p: any) => ({ time: tsUnix(p.ts), value: p.value })));
    s.bbL?.setData((data.overlays?.bb_lower ?? []).map((p: any) => ({ time: tsUnix(p.ts), value: p.value })));
    s.st?.setData((data.overlays?.supertrend ?? []).map((p: any) => ({ time: tsUnix(p.ts), value: p.value })));

    // Volume-profile levels as horizontal price lines (Phase 3.3): POC solid, VA dashed.
    priceLines.current.forEach((pl) => { try { s.candle?.removePriceLine(pl); } catch { /* gone */ } });
    priceLines.current = [];
    const vp = data.volume_profile;
    if (vp && s.candle) {
      const add = (price: number | null, color: string, title: string, dashed = false) => {
        if (price == null) return;
        priceLines.current.push(s.candle!.createPriceLine({
          price, color, lineWidth: 1, lineStyle: dashed ? 2 : 0, axisLabelVisible: true, title,
        }));
      };
      add(vp.poc, "#F0A35E", "POC");
      add(vp.vah, "#5A6273", "VAH", true);
      add(vp.val, "#5A6273", "VAL", true);
    }
    markerMap.current.clear();
    const markers: SeriesMarker<UTCTimestamp>[] = (data.markers ?? []).map((m: any) => {
      const t = tsUnix(m.ts);
      if (m.type === "signal") markerMap.current.set(Number(t), m);
      const buy = m.side === "BUY";
      return {
        time: t, position: buy ? "belowBar" : "aboveBar",
        color: m.type === "entry" ? C.brand : m.decision === "PASS" ? C.up : C.down,
        shape: buy ? "arrowUp" : "arrowDown", text: m.setup ?? m.type,
      } as SeriesMarker<UTCTimestamp>;
    });
    markers.sort((a, b) => Number(a.time) - Number(b.time));
    s.candle.setMarkers(markers);
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  return (
    <div className="flex min-h-0 flex-col rounded-panel border bg-surface">
      <div className="flex items-center gap-2 border-b px-2 py-1">
        <select value={instrument} onChange={(e) => setParams({ i: e.target.value })}
          className="rounded-control border bg-surface-raised px-1.5 py-0.5 text-dense text-text-hi outline-none">
          {instruments.map((i) => <option key={i} value={i}>{i}</option>)}
        </select>
        <div className="flex gap-0.5">
          {["5m", "15m", "day"].map((iv) => (
            <button key={iv} onClick={() => setTf(iv)}
              className={"rounded-control border px-1.5 py-0.5 text-micro " + (tf === iv ? "text-text-hi" : "text-text-lo")}
              style={tf === iv ? { borderColor: "var(--brand)" } : undefined}>{iv}</button>
          ))}
        </div>
        <span className="flex-1" />
        <span className="eyebrow">click a marker → gate trail</span>
      </div>
      <div className="flex min-h-0 flex-1">
        <div ref={elRef} className="min-h-0 min-w-0 flex-1" />
        <div className="w-28 shrink-0 border-l">
          <div className="eyebrow px-1.5 pt-1">Depth</div>
          <DepthLadder depth={data?.depth} />
        </div>
      </div>
    </div>
  );
}

export function Charts() {
  const [params] = useSearchParams();
  const [grid, setGrid] = useState<1 | 2 | 4>(1);
  const { data: market } = useQuery({ queryKey: ["market"], queryFn: api.market });
  const instruments = (market ?? []).map((r) => r.instrument);
  const primary = params.get("i") || instruments[2] || instruments[0] || "RELIANCE";
  const panelInstruments = [primary, ...instruments.filter((i) => i !== primary)].slice(0, grid);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b px-3 py-1.5">
        <span className="eyebrow">Charts</span>
        <div className="flex-1" />
        <div className="flex gap-1">
          {([1, 2, 4] as const).map((g) => (
            <button key={g} onClick={() => setGrid(g)}
              className={"rounded-control border px-2 py-0.5 text-micro " + (grid === g ? "text-text-hi" : "text-text-lo")}
              style={grid === g ? { borderColor: "var(--brand)" } : undefined}>{g}-up</button>
          ))}
        </div>
      </div>
      <div className="grid min-h-0 flex-1 gap-2 p-2" style={{ gridTemplateColumns: grid === 1 ? "1fr" : "1fr 1fr", gridAutoRows: grid <= 2 ? "1fr" : "minmax(0,1fr)" }}>
        {panelInstruments.map((inst, i) => <ChartPanel key={inst + i} instrument={inst} instruments={instruments} />)}
      </div>
    </div>
  );
}

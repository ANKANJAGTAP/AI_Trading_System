// Workspace panel registry — real, live content (each isolated in an ErrorBoundary so
// one panel crashing never takes down the workspace).
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { TickNum } from "@/components/TickNum";
import { Charts } from "@/screens/Charts";
import { Market } from "@/screens/Market";
import { Positions } from "@/screens/Positions";
import { Risk } from "@/screens/Risk";
import { Signals } from "@/screens/Signals";
import { api } from "@/lib/api";
import { fmtINR, pnlClass } from "@/lib/format";

function PnlPanel() {
  const { data: p } = useQuery({ queryKey: ["pnl"], queryFn: api.pnlToday, refetchInterval: 4000 });
  const ks = p && p.killswitch_limit ? Math.min(1, p.killswitch_used / p.killswitch_limit) : 0;
  return (
    <div className="flex h-full flex-col gap-2 p-4">
      <span className="eyebrow">Net P&amp;L · today</span>
      <div className={"mono font-semibold " + pnlClass(p?.net)} style={{ fontSize: 32, lineHeight: 1 }}>
        <TickNum value={p?.net} fmt={(v) => fmtINR(v)} />
      </div>
      <div className="flex gap-3 text-dense">
        <span className="text-text-lo">real <span className={"mono " + pnlClass(p?.realized)}>{fmtINR(p?.realized)}</span></span>
        <span className="text-text-lo">unreal <span className={"mono " + pnlClass(p?.unrealized)}>{fmtINR(p?.unrealized)}</span></span>
      </div>
      <div className="mt-1">
        <div className="mb-1 flex justify-between text-micro"><span className="eyebrow">kill-switch</span><span className="mono text-text-lo">{fmtINR(p?.killswitch_used)} / {fmtINR(p?.killswitch_limit)}</span></div>
        <div className="h-2 overflow-hidden rounded-full" style={{ background: "var(--surface-inset)" }}>
          <div className="h-full rounded-full" style={{ width: `${ks * 100}%`, background: ks >= 1 ? "var(--short)" : ks >= 0.75 ? "var(--warn)" : "var(--long)" }} />
        </div>
      </div>
    </div>
  );
}

const guard = (node: ReactNode) => <ErrorBoundary>{node}</ErrorBoundary>;

export interface PanelDef {
  title: string;
  render: () => ReactNode;
}

export const PANELS: Record<string, PanelDef> = {
  pnl: { title: "P&L Hero", render: () => guard(<PnlPanel />) },
  market: { title: "Market", render: () => guard(<Market />) },
  positions: { title: "Positions", render: () => guard(<Positions />) },
  signals: { title: "Signals", render: () => guard(<Signals />) },
  risk: { title: "Risk", render: () => guard(<Risk />) },
  chart: { title: "Chart", render: () => guard(<Charts />) },
};

export const PANEL_TYPES = Object.keys(PANELS);

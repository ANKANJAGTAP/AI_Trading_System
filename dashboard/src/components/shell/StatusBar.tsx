// Global Status Bar — mode badge, health, session, capital, margin gauge, day-P&L vs
// kill-switch gauge, open R, IST clock, guarded Pause + Flatten-All, density, ⌘K.
import { useQuery } from "@tanstack/react-query";
import { Command, ExternalLink, Pause } from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "@/lib/api";
import { clockIST, fmtINR, fmtNum, pnlClass } from "@/lib/format";
import { HoldButton } from "@/components/HoldButton";
import { DensityToggle } from "@/components/shell/DensityToggle";
import { InlineGauge, StatusDot } from "@/components/viz";
import { screenKeyForPath } from "@/screenRegistry";
import { useStore } from "@/store/store";

export function StatusBar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const mode = useStore((s) => s.mode);
  const setMode = useStore((s) => s.setMode);
  const conn = useStore((s) => s.connection);
  const toast = useStore((s) => s.toast);
  const loc = useLocation();
  const account = useQuery({ queryKey: ["account"], queryFn: api.account, refetchInterval: 5000 });
  const pnl = useQuery({ queryKey: ["pnl"], queryFn: api.pnlToday, refetchInterval: 4000 });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 5000 });
  const risk = useQuery({ queryKey: ["risk"], queryFn: api.risk, refetchInterval: 10000 });
  const [clock, setClock] = useState(clockIST());

  useEffect(() => {
    const id = setInterval(() => setClock(clockIST()), 1000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (account.data?.mode) setMode(account.data.mode);
  }, [account.data?.mode, setMode]);

  const live = mode === "live";
  const stale = conn !== "open" ? "stale" : "";
  const dot = conn !== "open" ? "warn" : health.data?.kill_switch_active ? "down" : "ok";
  const ksUsed = pnl.data?.killswitch_used ?? 0;
  const ksLimit = pnl.data?.killswitch_limit ?? 1;
  const modeColor = live ? "var(--mode-live)" : "var(--mode-sim)";

  return (
    <div className="flex h-9 items-center gap-3 border-b bg-surface px-3 text-dense">
      <span className="rounded-chip px-2 py-0.5 font-medium"
        style={{ color: modeColor, background: `color-mix(in srgb, ${modeColor} 16%, transparent)` }}>
        {live ? <span className="live-pulse">● LIVE</span> : "SIM"}
      </span>
      <StatusDot status={dot as "ok" | "warn" | "down"} pulse={dot === "down"} label={conn !== "open" ? "link" : undefined} />
      <span className="eyebrow">{health.data?.session_state ?? "—"}</span>
      <span className="h-4 w-px bg-line" />

      <span className={"flex items-center gap-1 " + stale}>
        <span className="eyebrow">cap</span>
        <span className="mono">{fmtINR(account.data?.live_capital)}</span>
      </span>
      <span className={"flex items-center gap-1 " + stale} title="margin used vs capital">
        <span className="eyebrow">mgn</span>
        <InlineGauge value={account.data?.used_margin ?? 0} max={account.data?.live_capital ?? 1} />
      </span>
      <span className={"flex items-center gap-1 " + stale} title="day P&L vs kill-switch limit">
        <span className="eyebrow">p&l</span>
        <span className={"mono " + pnlClass(pnl.data?.net)}>{fmtINR(pnl.data?.net)}</span>
        <InlineGauge value={ksUsed} max={ksLimit} warn={ksLimit * 0.75} />
      </span>
      <span className={"flex items-center gap-1 " + stale} title="open R vs portfolio limit">
        <span className="eyebrow">R</span>
        <span className="mono">{fmtNum(risk.data?.open_R ?? 0, 0)}/{fmtNum(risk.data?.portfolio_limit_R ?? 0, 0)}</span>
      </span>

      <div className="flex-1" />

      <button onClick={onOpenPalette} title="Command palette (Ctrl/Cmd-K)" aria-label="Command palette"
        className="flex items-center gap-1 rounded-control border px-2 py-0.5 text-text-lo">
        <Command size={12} /> ⌘K
      </button>
      <button
        onClick={() => {
          const k = screenKeyForPath(loc.pathname);
          window.open(`/popout/${k}`, k, "width=1280,height=860,noopener");
        }}
        title="Pop out current view to a new window" aria-label="Pop out current view"
        className="flex items-center gap-1 rounded-control border px-2 py-0.5 text-text-lo">
        <ExternalLink size={12} />
      </button>
      <DensityToggle />
      <button title="Pause new entries (existing positions still managed)" aria-label="Pause new entries"
        className="flex items-center gap-1 rounded-control border px-2 py-0.5 text-text-lo"
        onClick={async () => {
          try {
            await api.pause(true);
            toast("Engine paused — new entries blocked (open positions still managed)", "warn");
          } catch (e: any) {
            toast(String(e.message), "short");
          }
        }}>
        <Pause size={12} />
      </button>
      <HoldButton danger label="FLATTEN" onConfirm={async () => {
        try {
          await api.flatten();
          toast("Flatten-All sent — squaring off all positions", "short");
        } catch (e: any) {
          toast(String(e.message), "short");
        }
      }} />
      <span className="mono text-text-lo">{clock} IST</span>
    </div>
  );
}

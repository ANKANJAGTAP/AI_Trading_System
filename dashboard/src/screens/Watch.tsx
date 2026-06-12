// Mobile/tablet Watch view (frontend_v2 §8 F9) — read-only monitoring on a phone:
// P&L, kill-switch, health, positions, and the emergency Flatten-All. No entry controls.
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { HoldButton } from "@/components/HoldButton";
import { StatusDot } from "@/components/viz";
import { fmtINR, pnlClass } from "@/lib/format";
import { connectWs } from "@/lib/ws";
import { useStore } from "@/store/store";

export function Watch() {
  const toast = useStore((s) => s.toast);
  const mode = useStore((s) => s.mode);
  const setMode = useStore((s) => s.setMode);
  const pnl = useQuery({ queryKey: ["pnl"], queryFn: api.pnlToday, refetchInterval: 4000 });
  const positions = useQuery({ queryKey: ["positions"], queryFn: api.positions, refetchInterval: 5000 });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 6000 });
  const account = useQuery({ queryKey: ["account"], queryFn: api.account, refetchInterval: 8000 });

  useEffect(() => { connectWs(); }, []);
  useEffect(() => { if (account.data?.mode) setMode(account.data.mode); }, [account.data?.mode, setMode]);

  const p = pnl.data;
  const live = mode === "live";
  const ks = p && p.killswitch_limit ? Math.min(1, p.killswitch_used / p.killswitch_limit) : 0;
  const modeColor = live ? "var(--mode-live)" : "var(--mode-sim)";

  return (
    <div className="mx-auto flex min-h-screen max-w-xl flex-col gap-4 bg-ink p-4 text-text-hi">
      <div className="flex items-center justify-between">
        <span className="font-ui font-semibold tracking-tight text-brand">AEGIS · Watch</span>
        <span className="rounded-chip px-2 py-0.5 font-medium" style={{ color: modeColor, background: `color-mix(in srgb, ${modeColor} 16%, transparent)` }}>{live ? "● LIVE" : "SIM"}</span>
      </div>

      <div className="rounded-panel border bg-surface p-4">
        <span className="eyebrow">Net P&amp;L · today</span>
        <div className={"mono font-semibold " + pnlClass(p?.net)} style={{ fontSize: 40, lineHeight: 1.1 }}>{fmtINR(p?.net)}</div>
        <div className="mt-1 flex gap-4 text-dense">
          <span className="text-text-lo">real <span className={"mono " + pnlClass(p?.realized)}>{fmtINR(p?.realized)}</span></span>
          <span className="text-text-lo">unreal <span className={"mono " + pnlClass(p?.unrealized)}>{fmtINR(p?.unrealized)}</span></span>
        </div>
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-micro"><span className="eyebrow">kill-switch</span><span className="mono text-text-lo">{fmtINR(p?.killswitch_used)} / {fmtINR(p?.killswitch_limit)}</span></div>
          <div className="h-2.5 overflow-hidden rounded-full" style={{ background: "var(--surface-inset)" }}>
            <div className="h-full rounded-full" style={{ width: `${ks * 100}%`, background: ks >= 1 ? "var(--short)" : ks >= 0.75 ? "var(--warn)" : "var(--long)" }} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-panel border bg-surface p-3"><span className="eyebrow">capital</span><div className="mono">{fmtINR(account.data?.live_capital)}</div></div>
        <div className="rounded-panel border bg-surface p-3">
          <span className="eyebrow">health</span>
          <div className="mt-1 flex flex-col gap-1">
            <StatusDot status={health.data?.feed === "stale" || health.data?.feed === "unknown" ? "warn" : "ok"} label="feed" />
            <StatusDot status={health.data?.token === "ok" ? "ok" : "down"} label="token" />
            <StatusDot status={health.data?.kill_switch_active ? "down" : "ok"} label={health.data?.kill_switch_active ? "kill-switch ACTIVE" : "armed"} pulse={health.data?.kill_switch_active} />
          </div>
        </div>
      </div>

      <div className="flex-1 rounded-panel border bg-surface p-3">
        <span className="eyebrow">Positions · {positions.data?.length ?? 0}</span>
        <div className="mt-1 flex flex-col gap-1">
          {(positions.data ?? []).length === 0 ? <span className="text-dense text-text-faint">none open</span>
            : positions.data!.map((p) => (
              <div key={String(p.id)} className="flex items-center justify-between text-dense">
                <span className="truncate">{p.instrument}</span>
                <span className={"mono " + pnlClass(p.unrealized)}>{fmtINR(p.unrealized)}</span>
              </div>
            ))}
        </div>
      </div>

      <HoldButton danger label="FLATTEN ALL" ms={2500} className="w-full py-3 text-base"
        onConfirm={async () => { try { await api.flatten(); toast("Flatten-all queued", "short"); } catch (e: any) { toast(String(e.message), "short"); } }} />
      <div className="text-center text-micro text-text-faint">Read-only monitoring · emergency flatten only</div>
    </div>
  );
}

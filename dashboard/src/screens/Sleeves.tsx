// Sleeves (frontend_v2 §4.7) — capital allocation truth: cap vs deployed vs
// margin-bounded headroom, P&L + mini-curve, guarded enable/disable, allocation donut.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Donut } from "@/components/charts/Donut";
import { Sparkline, StatusDot } from "@/components/viz";
import { fmtINR, fmtPct, fmtR, pnlClass } from "@/lib/format";
import type { Sleeve } from "@/lib/types";
import { useStore } from "@/store/store";

const COLOR: Record<string, string> = {
  intraday_stocks: "var(--brand)", fno: "var(--info)", swing_stocks: "var(--long)", mcx_commodities: "var(--warn)",
};

function SleeveCard({ sl }: { sl: Sleeve }) {
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.sleeveToggle(sl.sleeve, enabled),
    onSuccess: (_d, enabled) => {
      toast(`${sl.sleeve} ${enabled ? "enabled" : "disabled — blocks NEW entries; open positions stay managed"}`, enabled ? "info" : "warn");
      setConfirm(false);
      qc.invalidateQueries({ queryKey: ["sleeves"] });
    },
    onError: (e: any) => toast(String(e.message), "short"),
  });
  const cap = sl.deployed + sl.margin_headroom;
  return (
    <div className="flex flex-col gap-2 rounded-panel border bg-surface p-3">
      <div className="flex items-center justify-between">
        <span className="font-ui text-text-hi">{sl.sleeve}</span>
        <div className="flex items-center gap-2">
          <StatusDot status={sl.enabled ? "ok" : "warn"} label={sl.enabled ? "on" : "off"} />
          {sl.enabled ? (
            <button onClick={() => setConfirm(true)} className="rounded-control border px-1.5 py-0.5 text-micro text-text-lo">disable</button>
          ) : (
            <button onClick={() => toggle.mutate(true)} className="rounded-control border px-1.5 py-0.5 text-micro" style={{ borderColor: "var(--brand)" }}>enable</button>
          )}
        </div>
      </div>
      {confirm && (
        <div className="rounded-control border px-2 py-1 text-micro" style={{ borderColor: "var(--warn)" }}>
          Disable blocks NEW entries; open positions stay managed.
          <div className="mt-1 flex gap-2">
            <button onClick={() => toggle.mutate(false)} className="text-short">confirm disable</button>
            <button onClick={() => setConfirm(false)} className="text-text-faint">cancel</button>
          </div>
        </div>
      )}
      <div>
        <div className="mb-1 flex justify-between text-micro text-text-lo">
          <span>cap {sl.cap_pct}% · used {fmtINR(sl.deployed)}</span>
          <span>headroom {fmtINR(sl.margin_headroom)}</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full" style={{ background: "var(--surface-inset)" }}>
          <div className="h-full rounded-full" style={{ width: `${cap ? Math.min(100, (sl.deployed / cap) * 100) : 0}%`, background: COLOR[sl.sleeve] ?? "var(--brand)" }} />
        </div>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex flex-col">
          <span className="eyebrow">day</span>
          <span className={"mono text-dense " + pnlClass(sl.day_pnl)}>{fmtINR(sl.day_pnl)}</span>
        </div>
        <div className="flex flex-col">
          <span className="eyebrow">cum</span>
          <span className={"mono text-dense " + pnlClass(sl.cum_pnl)}>{fmtINR(sl.cum_pnl)}</span>
        </div>
        <Sparkline data={(sl.curve ?? []).map((c) => c.value)} w={80} h={20} />
      </div>
      <div className="flex justify-between text-micro text-text-faint">
        <span>{sl.positions} open · W{sl.wins}/L{sl.losses}</span>
        <span>avg {fmtR(sl.avg_R)}</span>
      </div>
    </div>
  );
}

export function Sleeves() {
  const stale = useStore((s) => s.connection) !== "open";
  const sleeves = useQuery({ queryKey: ["sleeves"], queryFn: api.sleeves, refetchInterval: 6000 });
  const account = useQuery({ queryKey: ["account"], queryFn: api.account, refetchInterval: 6000 });
  const data = sleeves.data ?? [];
  const capital = account.data?.live_capital ?? 0;
  const deployedTotal = data.reduce((s, x) => s + x.deployed, 0);
  const idle = Math.max(0, capital - deployedTotal);
  const donut = [
    ...data.map((s) => ({ label: s.sleeve, value: s.deployed, color: COLOR[s.sleeve] ?? "var(--text-lo)" })),
    { label: "idle cash", value: idle, color: "var(--text-faint)" },
  ];

  return (
    <div className={"h-full overflow-auto p-3 " + (stale ? "stale" : "")}>
      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(12,minmax(0,1fr))" }}>
        <div className="rounded-panel border bg-surface p-3" style={{ gridColumn: "span 4" }}>
          <span className="eyebrow">Allocation</span>
          <div className="mt-2 flex items-center gap-4">
            <Donut data={donut} />
            <div className="flex flex-col gap-1 text-dense">
              {donut.map((d) => (
                <div key={d.label} className="flex items-center gap-2">
                  <span className="inline-block rounded-sm" style={{ width: 9, height: 9, background: d.color }} />
                  <span className="flex-1 text-text-lo">{d.label}</span>
                  <span className="mono">{fmtINR(d.value)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="grid gap-3" style={{ gridColumn: "span 8", gridTemplateColumns: "1fr 1fr" }}>
          {data.map((sl) => <SleeveCard key={sl.sleeve} sl={sl} />)}
        </div>
      </div>
    </div>
  );
}

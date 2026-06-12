// Controls (frontend_v2 §4.11) — the guarded action surface. Mode switch SIM<->LIVE
// (LIVE gated on the pre-live checklist + typed "LIVE" confirm), pause/resume, sleeve
// toggles, kill-switch reset, flatten-all, pre-live checklist.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useState } from "react";
import { api } from "@/lib/api";
import { HoldButton } from "@/components/HoldButton";
import { StatusDot } from "@/components/viz";
import { useStore } from "@/store/store";

function P({ title, span, accent, children }: { title: string; span: number; accent?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col rounded-panel border bg-surface p-3" style={{ gridColumn: `span ${span}`, borderColor: accent }}>
      <div className="mb-2 eyebrow">{title}</div>
      {children}
    </div>
  );
}

export function Controls() {
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const mode = useStore((s) => s.mode);
  const setMode = useStore((s) => s.setMode);
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 5000 });
  const sleeves = useQuery({ queryKey: ["sleeves"], queryFn: api.sleeves, refetchInterval: 6000 });
  const prelive = useQuery({ queryKey: ["prelive"], queryFn: api.prelive, refetchInterval: 10000 });
  const [liveToken, setLiveToken] = useState("");

  const preChecks = Object.entries(prelive.data ?? {});
  const allPass = preChecks.length > 0 && preChecks.every(([, v]) => v);
  const paused = health.data?.paused;
  const ksActive = health.data?.kill_switch_active;

  const modeMut = useMutation({
    mutationFn: (p: { mode: string; token?: string }) => api.setMode(p.mode, p.token),
    onSuccess: (_d, p) => { setMode(p.mode as any); toast(`Mode → ${p.mode}`, p.mode === "live" ? "short" : "info"); setLiveToken(""); qc.invalidateQueries({ queryKey: ["health"] }); },
    onError: (e: any) => toast(String(e.message), "short"),
  });
  const pauseMut = useMutation({
    mutationFn: (p: boolean) => api.pause(p),
    onSuccess: (_d, p) => { toast(p ? "Engine paused" : "Engine resumed", "warn"); qc.invalidateQueries({ queryKey: ["health"] }); },
    onError: (e: any) => toast(String(e.message), "short"),
  });
  const sleeveMut = useMutation({
    mutationFn: (p: { s: string; e: boolean }) => api.sleeveToggle(p.s, p.e),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sleeves"] }),
    onError: (e: any) => toast(String(e.message), "short"),
  });

  return (
    <div className="grid h-full gap-3 overflow-auto p-3" style={{ gridTemplateColumns: "repeat(12,minmax(0,1fr))", gridAutoRows: "min-content" }}>
      <P title="Execution Mode" span={6} accent={mode === "live" ? "var(--mode-live)" : undefined}>
        <div className="mb-3 flex items-center gap-3">
          <span className="rounded-chip px-2 py-0.5 font-medium" style={{ color: mode === "live" ? "var(--mode-live)" : "var(--mode-sim)", background: `color-mix(in srgb, ${mode === "live" ? "var(--mode-live)" : "var(--mode-sim)"} 16%, transparent)` }}>
            {mode === "live" ? "● LIVE" : "SIM"}
          </span>
          {mode === "live" ? (
            <button onClick={() => modeMut.mutate({ mode: "simulated_fill" })} className="rounded-control border px-2 py-1 text-dense">switch to SIM</button>
          ) : (
            <div className="flex items-center gap-2">
              <input value={liveToken} onChange={(e) => setLiveToken(e.target.value)} placeholder="type LIVE" disabled={!allPass}
                className="w-24 rounded-control border bg-surface-inset px-2 py-1 mono text-dense outline-none disabled:opacity-40" />
              <button disabled={!allPass || liveToken !== "LIVE"} onClick={() => modeMut.mutate({ mode: "live", token: "LIVE" })}
                className="rounded-control px-2 py-1 text-dense font-medium disabled:opacity-40" style={{ background: "var(--mode-live)", color: "var(--ink)" }}>GO LIVE</button>
            </div>
          )}
        </div>
        {!allPass && mode !== "live" && <div className="text-micro text-warn">Complete the pre-live checklist before going LIVE.</div>}
        <div className="text-micro text-text-faint">LIVE places real orders. SIM uses simulated fills.</div>
      </P>

      <P title="Engine + Safety" span={6}>
        <div className="mb-3 flex items-center gap-3">
          <StatusDot status={paused ? "warn" : "ok"} label={paused ? "paused" : "running"} />
          {paused
            ? <button onClick={() => pauseMut.mutate(false)} className="rounded-control border px-2 py-1 text-dense">resume</button>
            : <button onClick={() => pauseMut.mutate(true)} className="rounded-control border px-2 py-1 text-dense">pause new entries</button>}
        </div>
        <div className="mb-1 eyebrow">Kill-switch</div>
        <div className="flex flex-wrap items-center gap-3">
          <StatusDot status={ksActive ? "down" : "ok"} label={ksActive ? "ACTIVE" : "armed"} pulse={ksActive} />
          <HoldButton danger label="reset kill-switch" onConfirm={async () => { try { await api.ksReset(); toast("Kill-switch reset", "warn"); qc.invalidateQueries({ queryKey: ["health"] }); } catch (e: any) { toast(String(e.message), "short"); } }} />
          <HoldButton danger label="FLATTEN ALL" onConfirm={async () => { try { await api.flatten(); toast("Flatten-all queued", "short"); } catch (e: any) { toast(String(e.message), "short"); } }} />
        </div>
      </P>

      <P title="Sleeves" span={6}>
        <div className="flex flex-col gap-1">
          {(sleeves.data ?? []).map((sl) => (
            <div key={sl.sleeve} className="flex items-center justify-between text-dense">
              <span className="flex items-center gap-2"><StatusDot status={sl.enabled ? "ok" : "warn"} />{sl.sleeve}</span>
              <button onClick={() => sleeveMut.mutate({ s: sl.sleeve, e: !sl.enabled })} className="rounded-control border px-2 py-0.5 text-micro">{sl.enabled ? "disable" : "enable"}</button>
            </div>
          ))}
        </div>
        <div className="mt-2 text-micro text-text-faint">Disabling blocks NEW entries; open positions stay managed.</div>
      </P>

      <P title="Pre-live checklist" span={6}>
        <div className="flex flex-col gap-1">
          {preChecks.length === 0 ? <span className="text-dense text-text-faint">no checklist</span>
            : preChecks.map(([k, v]) => (
              <div key={k} className="flex items-center gap-2 text-dense">
                <StatusDot status={v ? "ok" : "down"} />
                <span className={v ? "text-text-lo" : "text-text-faint"}>{k.replace(/_/g, " ")}</span>
              </div>
            ))}
        </div>
        <div className="mt-2 text-micro" style={{ color: allPass ? "var(--long)" : "var(--warn)" }}>
          {allPass ? "✓ all checks pass — LIVE permitted" : "LIVE blocked until all checks pass"}
        </div>
      </P>
    </div>
  );
}

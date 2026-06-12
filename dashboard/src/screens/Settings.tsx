// Settings (frontend_v2 §4.12) — config editing within backend bounds (audited, applies
// on engine reload), system info, LLM provider, alert routing.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtINR } from "@/lib/format";
import { useStore } from "@/store/store";

function P({ title, span, children }: { title: string; span: number; children: ReactNode }) {
  return (
    <div className="flex flex-col rounded-panel border bg-surface p-3" style={{ gridColumn: `span ${span}` }}>
      <div className="mb-2 eyebrow">{title}</div>
      {children}
    </div>
  );
}
function Row({ k, v }: { k: string; v: ReactNode }) {
  return <div className="flex justify-between text-dense"><span className="text-text-lo">{k}</span><span className="mono">{v}</span></div>;
}

function EditRow({ path, label, value, bounds }: { path: string; label: string; value: number; bounds: [number, number] }) {
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const [lo, hi] = bounds;
  const valid = v >= lo && v <= hi;
  const mut = useMutation({
    mutationFn: () => api.putConfig(path, v),
    onSuccess: () => { toast(`${label} → ${v}% (recorded + audited; applies on engine reload)`, "info"); qc.invalidateQueries({ queryKey: ["config"] }); },
    onError: (e: any) => toast(String(e.message), "short"),
  });
  return (
    <div className="flex items-center gap-2 text-dense">
      <span className="w-44 text-text-lo">{label}</span>
      <input type="number" step="0.05" value={v} onChange={(e) => setV(+e.target.value)}
        className="w-24 rounded-control border bg-surface-inset px-2 py-0.5 mono outline-none" />
      <span className="text-micro text-text-faint">[{lo}–{hi}]</span>
      <button disabled={!valid || v === value} onClick={() => mut.mutate()}
        className="rounded-control border px-2 py-0.5 text-micro disabled:opacity-40" style={valid ? { borderColor: "var(--brand)" } : undefined}>apply</button>
      {!valid && <span className="text-micro text-short">out of bounds</span>}
    </div>
  );
}

export function Settings() {
  const mode = useStore((s) => s.mode);
  const { data: c } = useQuery({ queryKey: ["config"], queryFn: api.config });
  const editable = (c?.bounds?.editable ?? {}) as Record<string, [number, number]>;
  const labelFor = (key: string) => (key === "paper_per_trade_pct" ? "per-trade risk %" : key === "paper_daily_max_loss_pct" ? "daily max loss %" : key);

  return (
    <div className="grid h-full gap-3 overflow-auto p-3" style={{ gridTemplateColumns: "repeat(12,minmax(0,1fr))", gridAutoRows: "min-content" }}>
      <P title="Risk config · paper overlay" span={6}>
        <div className="flex flex-col gap-2">
          {Object.entries(editable).map(([path, b]) => {
            const key = path.split(".").pop() as string;
            return <EditRow key={path} path={path} label={labelFor(key)} value={Number(c?.risk?.[key] ?? 0)} bounds={b} />;
          })}
        </div>
        <div className="mt-2 text-micro text-text-faint">Canonical spec risk stays 1% / 3%; these edit the paper-run overlay only. Every edit is audited and applies on engine reload.</div>
      </P>

      <P title="System" span={6}>
        <Row k="mode" v={mode} />
        <Row k="LLM provider" v={c?.system?.llm_provider ?? "—"} />
        <Row k="paper capital" v={fmtINR(c?.system?.paper_capital)} />
      </P>

      <P title="Strategy parameters · read-only" span={6}>
        <details className="text-dense">
          <summary className="cursor-pointer text-text-lo">view raw config</summary>
          <pre className="mono mt-1 whitespace-pre-wrap break-words text-micro text-text-faint">{JSON.stringify(c?.strategy_params ?? {}, null, 1)}</pre>
        </details>
      </P>

      <P title="Alert routing" span={6}>
        <div className="text-dense text-text-lo">
          Alerts route through the engine's configured channel (Telegram / webhook) set in deployment env.
          Critical events — kill-switch, fills, errors — are published to the event bus and surfaced here as toasts + in the Activity feed.
        </div>
      </P>
    </div>
  );
}

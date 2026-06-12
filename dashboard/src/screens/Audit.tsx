// Audit + reconstruction (frontend_v2 §4.10) — the trust layer. Searchable event log;
// pick a correlation ID -> full causal chain (signal -> gates -> events -> positions),
// exportable. Every executed trade is fully reconstructable from here.
import { useQuery } from "@tanstack/react-query";
import { Download, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { GateTrail } from "@/components/GateTrail";
import { fmtINR, fmtNum, fmtTimeIST, pnlClass } from "@/lib/format";
import { useStore } from "@/store/store";

function eventColor(t: string) {
  if (!t) return "var(--text-lo)";
  if (t.startsWith("control")) return "var(--warn)";
  if (t.includes("order") || t.includes("fill")) return "var(--brand)";
  if (t.includes("signal")) return "var(--info)";
  if (t.includes("alert") || t.includes("kill")) return "var(--short)";
  return "var(--text-lo)";
}
function downloadJSON(name: string, obj: any) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

function Reconstruction({ cid }: { cid: string }) {
  const { data, isLoading } = useQuery({ queryKey: ["recon", cid], queryFn: () => api.reconstruct(cid) });
  if (isLoading) return <div className="p-4 text-dense text-text-faint">Reconstructing…</div>;
  if (!data) return null;
  const sig = data.signal;
  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex items-center gap-2">
        <span className="font-ui text-text-hi">Reconstruction</span>
        <span className="mono text-micro text-text-faint">{cid}</span>
        <span className="flex-1" />
        <button onClick={() => downloadJSON(`recon-${cid}.json`, data)} className="flex items-center gap-1 rounded-control border px-2 py-0.5 text-micro">
          <Download size={11} /> export
        </button>
      </div>

      {sig ? (
        <div className="rounded-panel border bg-surface-inset p-2 text-dense">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-medium text-text-hi">{sig.instrument}</span>
            <span className="eyebrow">{sig.sleeve}</span>
            <span className="eyebrow">{sig.setup}</span>
            <span style={{ color: sig.decision === "PASS" ? "var(--long)" : "var(--short)" }}>{sig.decision}</span>
            <span className="mono text-text-lo">conf {fmtNum(sig.confidence, 2)}</span>
          </div>
          {sig.reason && <div className="mt-1 text-text-lo">{sig.reason}</div>}
        </div>
      ) : <div className="text-dense text-text-faint">No signal row for this id — a control/system event.</div>}

      {data.gates?.length > 0 && (
        <div>
          <span className="eyebrow">Gate Trail</span>
          <GateTrail gates={data.gates} confidence={sig?.confidence} />
          <div className="mt-1 flex flex-col gap-0.5">
            {data.gates.map((g: any, i: number) => (
              <details key={i} className="text-micro">
                <summary className="cursor-pointer">
                  <span style={{ color: g.pass ? "var(--long)" : "var(--short)" }}>{g.pass ? "✓" : "✗"}</span> {g.name}{" "}
                  <span className="text-text-faint">({fmtNum(g.score, 2)})</span>
                </summary>
                <pre className="mono whitespace-pre-wrap pl-4 text-text-faint">{JSON.stringify(g.detail, null, 1)}</pre>
              </details>
            ))}
          </div>
        </div>
      )}

      <div>
        <span className="eyebrow">Timeline · {data.events?.length ?? 0} events</span>
        <div className="mt-1 flex flex-col gap-0.5">
          {(data.events ?? []).map((e: any, i: number) => (
            <div key={i} className="flex gap-2 border-l-2 pl-2 text-micro" style={{ borderColor: eventColor(e.event_type) }}>
              <span className="mono w-16 text-text-faint">{fmtTimeIST(e.ts)}</span>
              <span className="eyebrow w-28 shrink-0" style={{ color: eventColor(e.event_type) }}>{e.event_type}</span>
              <span className="flex-1 text-text-lo">{e.message}</span>
            </div>
          ))}
        </div>
      </div>

      {data.positions?.length > 0 && (
        <div>
          <span className="eyebrow">Positions</span>
          <div className="mt-1 flex flex-col gap-0.5 text-dense">
            {data.positions.map((p: any) => (
              <div key={p.id} className="flex gap-3">
                <span className="w-32 truncate text-text-hi">{p.instrument}</span>
                <span>{p.side} {p.qty}</span>
                <span className="mono">@ {fmtNum(p.entry, 1)}</span>
                <span className="eyebrow">{p.status}</span>
                <span className={"mono " + pnlClass(p.realized)}>{fmtINR(p.realized)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function Audit() {
  const stale = useStore((s) => s.connection) !== "open";
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [cid, setCid] = useState<string | null>(null);
  const { data } = useQuery({ queryKey: ["audit", type], queryFn: () => api.audit({ limit: 300, event_type: type || undefined }), refetchInterval: 8000 });
  const events = data ?? [];
  const types = useMemo(() => Array.from(new Set(events.map((e: any) => e.event_type))).sort(), [events]);
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    if (!q) return events;
    return events.filter((e: any) =>
      [e.message, e.component, e.correlation_id, e.event_type].some((x) => (x || "").toLowerCase().includes(q)));
  }, [events, search]);

  return (
    <div className="flex h-full min-h-0">
      <div className="flex w-[440px] shrink-0 flex-col border-r">
        <div className="flex items-center gap-2 border-b px-3 py-1.5">
          <span className="eyebrow">Audit</span>
          <div className="flex items-center gap-1 rounded-control border px-2 py-0.5">
            <Search size={12} className="text-text-faint" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="cid / instrument / message…"
              className="w-40 bg-transparent text-dense outline-none placeholder:text-text-faint" />
          </div>
          <select value={type} onChange={(e) => setType(e.target.value)} className="rounded-control border bg-surface-raised px-1 py-0.5 text-micro outline-none">
            <option value="">all types</option>
            {types.map((t) => <option key={t as string} value={t as string}>{t as string}</option>)}
          </select>
        </div>
        <div className={"flex-1 overflow-auto " + (stale ? "stale" : "")}>
          {filtered.length === 0 ? <div className="py-8 text-center text-dense text-text-faint">No audit events.</div>
            : filtered.map((e: any, i: number) => (
              <button key={i} onClick={() => e.correlation_id && setCid(e.correlation_id)}
                className={"flex w-full items-center gap-2 border-b border-line px-3 py-1 text-left text-micro hover:bg-surface-raised " + (cid && e.correlation_id === cid ? "bg-surface-raised" : "")}>
                <span className="mono w-16 text-text-faint">{fmtTimeIST(e.ts)}</span>
                <span className="eyebrow w-28 shrink-0" style={{ color: eventColor(e.event_type) }}>{e.event_type}</span>
                <span className="flex-1 truncate text-text-lo">{e.message}</span>
                {e.correlation_id && <span className="mono text-text-faint">{e.correlation_id.slice(0, 8)}</span>}
              </button>
            ))}
        </div>
      </div>
      <div className="min-w-0 flex-1 overflow-auto">
        {cid ? <Reconstruction cid={cid} /> : <div className="p-8 text-center text-dense text-text-faint">Select an event with a correlation ID to reconstruct the full decision chain.</div>}
      </div>
    </div>
  );
}

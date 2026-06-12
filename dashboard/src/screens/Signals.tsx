// Signals + Gate Trail + Rejection Analytics (frontend_v2 §4.5) — the window into the
// system's reasoning, plus aggregate insight into why trades fire or don't.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { GateTrail } from "@/components/GateTrail";
import { fmtTimeIST } from "@/lib/format";
import { useStore } from "@/store/store";

type Filter = "all" | "PASS" | "REJECT";

function decisionColor(d?: string) {
  return d === "PASS" ? "var(--long)" : d === "REJECT" ? "var(--short)" : "var(--text-lo)";
}

function Detail({ sig, animate }: { sig: any; animate: boolean }) {
  if (!sig) return <div className="p-6 text-center text-dense text-text-faint">Select a signal to see its Gate Trail.</div>;
  const decision = sig.decision ?? (sig.status === "executed" ? "PASS" : sig.status === "skip" ? "REJECT" : sig.status);
  const reject = sig.reject_gate ?? (sig.gates ?? []).find((g: any) => !g.pass)?.name;
  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex items-center gap-3">
        <span className="font-ui text-text-hi">{sig.instrument}</span>
        <span className="eyebrow">{sig.sleeve}</span>
        {sig.setup && <span className="eyebrow">{sig.setup}</span>}
        <span className="rounded-chip px-2 py-0.5 text-micro" style={{ color: decisionColor(decision), background: `color-mix(in srgb, ${decisionColor(decision)} 14%, transparent)` }}>{decision ?? "—"}</span>
        {sig.confidence != null && <span className="mono text-dense text-text-lo">conf {Number(sig.confidence).toFixed(2)}</span>}
        <span className="flex-1" />
        <span className="mono text-micro text-text-faint">{fmtTimeIST(sig.ts)}</span>
      </div>
      <GateTrail key={sig.correlation_id ?? sig.id ?? "x"} gates={sig.gates ?? []} confidence={sig.confidence} llm={sig.llm} animate={animate} />
      {reject && <div className="text-dense"><span className="eyebrow">rejected at</span> <span className="text-short">{reject}</span></div>}
      {sig.reason && <div className="text-dense text-text-lo">{sig.reason}</div>}
      {sig.llm && (
        <div className="text-dense">
          <span className="eyebrow">LLM verdict</span>
          <div className="text-text-lo">{sig.llm.veto ? "VETO" : "no veto"} · {sig.llm.sentiment ?? ""} · {sig.llm.event_risk ?? ""}</div>
          {sig.llm.reason && <div className="text-micro text-text-faint">{sig.llm.reason}</div>}
        </div>
      )}
    </div>
  );
}

function RejectionAnalytics() {
  const { data } = useQuery({ queryKey: ["rejections"], queryFn: api.rejections, refetchInterval: 10000 });
  const byGate = data?.by_gate ?? [];
  const maxC = Math.max(1, ...byGate.map((g: any) => g.count));
  return (
    <div className="grid gap-3 p-3" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
      <div>
        <span className="eyebrow">Rejecting gates</span>
        <div className="mt-1 flex flex-col gap-1">
          {byGate.length === 0 && <span className="text-micro text-text-faint">none in window</span>}
          {byGate.map((g: any) => (
            <div key={g.gate} className="flex items-center gap-2 text-dense">
              <span className="w-24 truncate text-text-lo">{g.gate}</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full" style={{ background: "var(--surface-inset)" }}>
                <div className="h-full rounded-full" style={{ width: `${(g.count / maxC) * 100}%`, background: "var(--short)" }} />
              </div>
              <span className="mono text-micro">{g.count}</span>
            </div>
          ))}
        </div>
      </div>
      <div>
        <span className="eyebrow">Reasons</span>
        <div className="mt-1 flex flex-col gap-0.5">
          {(data?.by_reason ?? []).map((r: any, i: number) => (
            <div key={i} className="flex justify-between text-dense"><span className="truncate text-text-lo">{r.reason}</span><span className="mono text-micro">{r.count}</span></div>
          ))}
          {(!data?.by_reason || data.by_reason.length === 0) && <span className="text-micro text-text-faint">none in window</span>}
        </div>
      </div>
      <div>
        <span className="eyebrow">Near misses</span>
        <div className="mt-1 flex flex-col gap-0.5">
          {(data?.near_misses ?? []).map((n: any, i: number) => (
            <div key={i} className="flex justify-between text-dense">
              <span className="truncate text-text-lo">{n.instrument}</span>
              <span className="mono text-micro">{n.passed_gates}/{n.total_gates}</span>
            </div>
          ))}
          {(!data?.near_misses || data.near_misses.length === 0) && <span className="text-micro text-text-faint">none in window</span>}
        </div>
      </div>
    </div>
  );
}

export function Signals() {
  const stale = useStore((s) => s.connection) !== "open";
  const lastSignal = useStore((s) => s.lastSignal);
  const [filter, setFilter] = useState<Filter>("all");
  const [pinned, setPinned] = useState<any | null>(null);
  const { data } = useQuery({ queryKey: ["signals", filter], queryFn: () => api.signals(filter === "all" ? undefined : filter), refetchInterval: 5000 });
  const list = data ?? [];
  const selected = pinned ?? lastSignal ?? list[0];
  const animate = !pinned && !!lastSignal; // live trail animates when auto-showing the latest

  return (
    <div className="flex h-full min-h-0">
      {/* list */}
      <div className="flex w-80 shrink-0 flex-col border-r">
        <div className="flex items-center gap-1 border-b px-3 py-1.5">
          <span className="eyebrow">Signals</span>
          <span className="flex-1" />
          {(["all", "PASS", "REJECT"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)}
              className={"rounded-control border px-1.5 py-0.5 text-micro " + (filter === f ? "text-text-hi" : "text-text-lo")}
              style={filter === f ? { borderColor: "var(--brand)" } : undefined}>{f}</button>
          ))}
        </div>
        <div className={"flex-1 overflow-auto " + (stale ? "stale" : "")}>
          {list.length === 0 ? (
            <div className="py-8 text-center text-dense text-text-faint">No signals yet — they stream as the engine evaluates.</div>
          ) : list.map((s) => (
            <button key={s.id} onClick={() => setPinned(s)}
              className={"flex w-full items-center gap-2 border-b border-line px-3 py-1.5 text-left text-dense hover:bg-surface-raised " + (selected?.id === s.id ? "bg-surface-raised" : "")}>
              <span className="inline-block rounded-full" style={{ width: 6, height: 6, background: decisionColor(s.decision) }} />
              <span className="w-20 shrink-0 truncate text-text-hi">{s.instrument}</span>
              <span className="flex-1 truncate text-text-faint">{s.setup ?? ""}</span>
              {s.decision === "REJECT" && s.reject_gate && <span className="text-micro text-short">{s.reject_gate}</span>}
              <span className="mono text-micro text-text-lo">{Number(s.confidence ?? 0).toFixed(2)}</span>
            </button>
          ))}
        </div>
        {pinned && <button onClick={() => setPinned(null)} className="border-t py-1 text-micro text-text-faint hover:text-text-lo">← back to live</button>}
      </div>
      {/* detail + rejection analytics */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-auto border-b">
          <Detail sig={selected} animate={animate} />
        </div>
        <div className="shrink-0">
          <div className="border-b px-3 py-1 eyebrow">Rejection Analytics · last 24h</div>
          <RejectionAnalytics />
        </div>
      </div>
    </div>
  );
}

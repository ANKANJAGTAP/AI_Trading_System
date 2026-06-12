// Inspector dock (right) — contextual detail for the selected position/signal/strike.
import { X } from "lucide-react";
import { GateTrail } from "@/components/GateTrail";
import { fmtNum, fmtPct } from "@/lib/format";
import { useStore } from "@/store/store";

function StrikeDetail({ data }: { data: any }) {
  const row = (k: string, v: string) => (
    <div className="flex justify-between"><span className="text-text-faint">{k}</span><span>{v}</span></div>
  );
  const Side = ({ label, c, elig }: { label: string; c: any; elig?: string }) => (
    <div className="flex-1">
      <div className="eyebrow mb-1">{label}</div>
      {c ? (
        <div className="mono flex flex-col gap-0.5 text-dense">
          {row("LTP", fmtNum(c.ltp, 1))}{row("OI", fmtNum(c.oi, 0))}{row("IV", fmtPct((c.iv ?? 0) * 100, 1, false))}
          {row("Δ", fmtNum(c.delta, 3))}{row("Θ", fmtNum(c.theta, 3))}{row("Γ", fmtNum(c.gamma, 5))}{row("V", fmtNum(c.vega, 3))}
        </div>
      ) : <span className="text-dense text-text-faint">—</span>}
      {elig && <div className="mt-1 text-micro text-brand">{elig}</div>}
    </div>
  );
  return (
    <div>
      <div className="mb-2 font-ui text-text-hi">Strike {fmtNum(data.strike, 0)}</div>
      <div className="flex gap-4">
        <Side label="Call" c={data.call} elig={data.eligibility?.call} />
        <Side label="Put" c={data.put} elig={data.eligibility?.put} />
      </div>
    </div>
  );
}

function SignalDetail({ data }: { data: any }) {
  // Accepts a signal object OR a reconstruction ({ signal, gates, events, positions }).
  const sig = data.signal ?? data;
  const gates = data.gates ?? data.signal?.gates ?? [];
  const confidence = data.confidence ?? sig?.confidence ?? null;
  const llm = data.llm ?? sig?.llm ?? null;
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 text-dense">
        <div><span className="eyebrow">instrument</span><div className="mono">{sig?.instrument ?? "—"}</div></div>
        <div><span className="eyebrow">sleeve</span><div>{sig?.sleeve ?? "—"}</div></div>
        <div><span className="eyebrow">setup</span><div>{sig?.setup ?? "—"}</div></div>
        <div><span className="eyebrow">decision</span><div className={sig?.decision === "PASS" ? "text-long" : "text-short"}>{sig?.decision ?? "—"}</div></div>
        {confidence != null && <div><span className="eyebrow">confidence</span><div className="mono">{Number(confidence).toFixed(2)}</div></div>}
        {sig?.reason && <div className="col-span-2"><span className="eyebrow">reason</span><div className="text-text-lo">{sig.reason}</div></div>}
      </div>
      {gates.length > 0 && (
        <div>
          <span className="eyebrow">Gate Trail</span>
          <GateTrail gates={gates} confidence={confidence} llm={llm} />
        </div>
      )}
      {llm && (
        <div className="text-dense">
          <span className="eyebrow">LLM verdict</span>
          <div className="text-text-lo">{llm.veto ? "VETO" : "no veto"} · {llm.sentiment ?? ""} · {llm.event_risk ?? ""}</div>
          {llm.reason && <div className="text-micro text-text-faint">{llm.reason}</div>}
        </div>
      )}
    </div>
  );
}

export function Inspector() {
  const insp = useStore((s) => s.inspector);
  const close = useStore((s) => s.closeInspector);
  if (!insp.open) return null;
  const isSignal = insp.kind === "signal" && (insp.data?.gates || insp.data?.signal);
  return (
    <aside className="flex w-80 shrink-0 flex-col border-l bg-surface">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="eyebrow">Inspector · {insp.kind ?? ""}</span>
        <button onClick={close} className="text-text-faint hover:text-text-hi" title="Close inspector">
          <X size={14} />
        </button>
      </div>
      <div className="flex-1 overflow-auto p-3 text-dense">
        {isSignal ? <SignalDetail data={insp.data} />
          : insp.kind === "strike" ? <StrikeDetail data={insp.data} />
          : <pre className="mono whitespace-pre-wrap break-words text-text-lo">{JSON.stringify(insp.data, null, 2)}</pre>}
      </div>
    </aside>
  );
}

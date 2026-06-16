// Go-Live readiness: the real pre-live checks (P0#2) + compliance (P9) + live
// mode/kill-switch state. A live flip is blocked until overall == pass.
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { api } from "@/lib/api";

const COLOR: Record<string, string> = { pass: "var(--long)", warn: "var(--warn)", fail: "var(--short)" };

function icon(s: string) {
  if (s === "pass") return <CheckCircle2 size={15} />;
  if (s === "warn") return <AlertTriangle size={15} />;
  return <XCircle size={15} />;
}

export function PreLiveReadiness() {
  const cl = useQuery({ queryKey: ["prelive"], queryFn: () => api.prelive(), refetchInterval: 15000 });
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.health(), refetchInterval: 8000 });

  const overall: string = cl.data?.overall ?? "…";
  const checks: any[] = cl.data?.checks ?? [];
  const h: any = health.data ?? {};

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b px-3 py-2">
        <span className="eyebrow">Go-Live Readiness</span>
        <div
          className="flex items-center gap-1.5 rounded-control border px-2 py-0.5"
          style={{ borderColor: COLOR[overall] ?? "var(--line)" }}
        >
          <span style={{ color: COLOR[overall] ?? "var(--text-lo)" }}>{icon(overall)}</span>
          <span className="eyebrow" style={{ color: COLOR[overall] ?? "var(--text-lo)" }}>
            {String(overall).toUpperCase()}
          </span>
        </div>
        <div className="flex-1" />
        <span className="text-micro text-text-faint">
          mode <span className="mono text-text-lo">{h.mode ?? "?"}</span> · kill-switch{" "}
          <span style={{ color: h.kill_switch_active ? "var(--short)" : "var(--long)" }}>
            {h.kill_switch_active ? "ACTIVE" : "clear"}
          </span>{" "}
          · live F&amp;O <span className="mono">{h.fno_live_structures_enabled ? "on" : "off"}</span>
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        <div className="rounded-panel border bg-surface">
          <div className="border-b px-3 py-1.5 eyebrow">Pre-live checks · {checks.length}</div>
          <table className="w-full text-dense">
            <thead className="text-text-lo">
              <tr>
                <th className="w-8 px-3 py-1 text-left eyebrow"></th>
                <th className="px-3 py-1 text-left eyebrow">check</th>
                <th className="px-3 py-1 text-left eyebrow">detail</th>
              </tr>
            </thead>
            <tbody>
              {checks.map((c: any) => (
                <tr key={c.name} className="border-b border-line">
                  <td className="px-3 py-1.5" style={{ color: COLOR[c.status] ?? "var(--text-lo)" }}>
                    {icon(c.status)}
                  </td>
                  <td className="px-3 py-1.5 text-text-hi">{c.name}</td>
                  <td className="px-3 py-1.5 text-micro text-text-lo">{c.detail}</td>
                </tr>
              ))}
              {checks.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-3 py-2 text-text-faint">
                    Loading checks…
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-micro text-text-faint">
          A live flip is blocked until <span className="text-text-lo">overall = pass</span>. Set algo_id + static_ip,
          whitelist the IP at Kite, reset the kill-switch, then re-check. (See COMPLIANCE.md.)
        </p>
      </div>
    </div>
  );
}

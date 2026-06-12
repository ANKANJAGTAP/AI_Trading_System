// Single-operator gate. Captures the API bearer token (when the backend runs with
// API_AUTH_TOKEN set) and stores a time-limited local session. The token is sent on
// every REST/WS call (see lib/api.ts, lib/ws.ts). Leave the token blank only when the
// backend has auth disabled (trusted localhost dev).
import { ShieldCheck } from "lucide-react";
import { useState, type ReactNode } from "react";

const KEY = "aegis.session";
const TOKEN_KEY = "aegis.token";
const TTL_MS = 12 * 60 * 60 * 1000; // 12h — re-prompt after expiry

function validSession(): boolean {
  try {
    const ts = Number(localStorage.getItem(KEY));
    return Number.isFinite(ts) && ts > 0 && Date.now() - ts < TTL_MS;
  } catch {
    return false;
  }
}

export function LoginGate({ children }: { children: ReactNode }) {
  const [authed, setAuthed] = useState(validSession);
  const [token, setToken] = useState("");
  if (authed) return <>{children}</>;

  const enter = () => {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
      localStorage.setItem(KEY, String(Date.now()));
    } catch {
      /* ignore storage failure */
    }
    setAuthed(true);
  };

  return (
    <div className="flex h-screen items-center justify-center bg-ink">
      <div className="w-80 rounded-panel border bg-surface-raised p-6 text-center">
        <div className="mb-3 flex justify-center text-brand"><ShieldCheck size={28} /></div>
        <div className="font-ui text-lg font-semibold tracking-tight">AEGIS</div>
        <div className="mb-4 text-dense text-text-lo">Operator console</div>
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && enter()}
          placeholder="API token (blank if auth disabled)"
          className="mb-3 w-full rounded-control border bg-surface-inset px-2 py-1.5 text-dense outline-none"
        />
        <button
          onClick={enter}
          className="w-full rounded-control py-2 font-medium"
          style={{ background: "var(--brand)", color: "var(--ink)" }}
        >
          Enter console
        </button>
        <div className="mt-3 text-micro text-text-faint">Session expires after 12h · token sent as Bearer auth</div>
      </div>
    </div>
  );
}

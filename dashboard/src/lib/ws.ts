// WebSocket client: connect, reconnect-with-backoff, route events to the store.
// "stale" in the UI is driven by connection !== "open" (a drop), per frontend_v2 §5.
import { useStore } from "@/store/store";

let socket: WebSocket | null = null;
let backoff = 1000;
let manualClose = false;

function wsUrl(): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws`;
}

// Token travels in the Sec-WebSocket-Protocol subprotocol ("bearer,<token>"),
// never the query string — keeps it out of logs/proxies/browser history (#20).
function wsToken(): string | null {
  return typeof localStorage !== "undefined" ? localStorage.getItem("aegis.token") : null;
}

export function connectWs(): void {
  manualClose = false;
  useStore.getState().setConnection("connecting");
  try {
    const tok = wsToken();
    socket = tok ? new WebSocket(wsUrl(), ["bearer", tok]) : new WebSocket(wsUrl());
  } catch {
    scheduleReconnect();
    return;
  }
  socket.onopen = () => {
    backoff = 1000;
    useStore.getState().setConnection("open");
  };
  socket.onmessage = (ev) => {
    try {
      useStore.getState().applyEvent(JSON.parse(ev.data));
    } catch {
      /* ignore malformed frame */
    }
  };
  socket.onclose = () => {
    useStore.getState().setConnection("closed");
    if (!manualClose) scheduleReconnect();
  };
  socket.onerror = () => {
    try {
      socket?.close();
    } catch {
      /* ignore */
    }
  };
}

function scheduleReconnect(): void {
  window.setTimeout(connectWs, backoff);
  backoff = Math.min(backoff * 2, 15000);
}

// Forced disconnect (e.g. the F0 acceptance test) — drops the stream so the UI degrades.
export function forceDisconnect(): void {
  manualClose = true;
  try {
    socket?.close();
  } catch {
    /* ignore */
  }
  useStore.getState().setConnection("closed");
}

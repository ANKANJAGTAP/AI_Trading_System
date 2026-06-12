// Global client/stream state (Zustand): WS connection, mode (Mode Frame), live LTPs,
// last signal (Gate Trail), alerts, inspector dock, density, toasts.
import { create } from "zustand";
import type { Mode, WsEvent } from "@/lib/types";

export type Conn = "connecting" | "open" | "closed";
export type Density = "comfortable" | "compact" | "ultra";

export interface Toast {
  id: number;
  title: string;
  kind: "info" | "long" | "short" | "warn";
}

export interface ActivityItem {
  id: number;
  ts: string;
  kind: "signal" | "order" | "alert";
  data: any;
}

interface State {
  connection: Conn;
  mode: Mode;
  density: Density;
  ltps: Record<string, number>;
  lastSignal: any | null;
  alerts: any[];
  activity: ActivityItem[];
  inspector: { open: boolean; kind?: string; data?: any };
  toasts: Toast[];

  setConnection: (c: Conn) => void;
  setMode: (m: Mode) => void;
  setDensity: (d: Density) => void;
  applyEvent: (e: WsEvent) => void;
  openInspector: (kind: string, data: any) => void;
  closeInspector: () => void;
  toast: (title: string, kind?: Toast["kind"]) => void;
  dismissToast: (id: number) => void;
}

const initialDensity = ((typeof localStorage !== "undefined" && localStorage.getItem("aegis.density")) ||
  "comfortable") as Density;

export const useStore = create<State>((set, get) => ({
  connection: "connecting",
  mode: "simulated_fill",
  density: initialDensity,
  ltps: {},
  lastSignal: null,
  alerts: [],
  activity: [],
  inspector: { open: false },
  toasts: [],

  setConnection: (connection) => set({ connection }),
  setMode: (mode) => set({ mode }),
  setDensity: (density) => {
    try {
      localStorage.setItem("aegis.density", density);
    } catch {
      /* ignore */
    }
    document.documentElement.dataset.density = density;
    set({ density });
  },

  applyEvent: (e) => {
    const s = get();
    const push = (kind: ActivityItem["kind"], data: any) =>
      [{ id: Date.now() + Math.random(), ts: e.ts, kind, data }, ...s.activity].slice(0, 120);
    switch (e.type) {
      case "price_update":
        set({ ltps: { ...s.ltps, ...((e.payload && e.payload.ltps) || {}) } });
        break;
      case "mode_changed":
        if (e.payload?.mode) set({ mode: e.payload.mode });
        break;
      case "signal_evaluated":
        set({ lastSignal: e.payload, activity: push("signal", e.payload) });
        break;
      case "order_event":
        set({ activity: push("order", e.payload) });
        break;
      case "alert":
        s.toast(e.payload?.message ?? "alert", e.payload?.severity === "critical" ? "short" : "warn");
        set({ alerts: [e.payload, ...s.alerts].slice(0, 50), activity: push("alert", e.payload) });
        break;
      default:
        break;
    }
  },

  openInspector: (kind, data) => set({ inspector: { open: true, kind, data } }),
  closeInspector: () => set({ inspector: { open: false } }),

  toast: (title, kind = "info") => {
    const id = Date.now() + Math.random();
    set({ toasts: [...get().toasts, { id, title, kind }] });
    setTimeout(() => get().dismissToast(id), 4500);
  },
  dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));

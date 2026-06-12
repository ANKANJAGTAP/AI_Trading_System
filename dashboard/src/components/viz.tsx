// Micro-visualization vocabulary (frontend_v2 §2.4) — the key to density. Reused everywhere.
import type { ReactNode } from "react";
import { fmtR } from "@/lib/format";

export function Sparkline({ data, w = 64, h = 18, className }: { data: number[]; w?: number; h?: number; className?: string }) {
  if (!data || data.length < 2) return <svg width={w} height={h} className={className} aria-hidden />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const rng = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / rng) * (h - 2) - 1}`).join(" ");
  const up = data[data.length - 1] >= data[0];
  return (
    <svg width={w} height={h} className={className} preserveAspectRatio="none" aria-hidden>
      <polyline points={pts} fill="none" stroke={up ? "var(--long)" : "var(--short)"} strokeWidth={1.25} strokeLinejoin="round" />
    </svg>
  );
}

// value-vs-limit bar with optional warn threshold
export function InlineGauge({ value, max, warn, w = 84, h = 8, className }:
  { value: number; max: number; warn?: number; w?: number; h?: number; className?: string }) {
  const pct = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const color = warn != null && value >= warn ? "var(--warn)" : value >= max && max > 0 ? "var(--short)" : "var(--brand)";
  return (
    <span className={"inline-block align-middle " + (className ?? "")} style={{ width: w, height: h }}>
      <span className="block rounded-full overflow-hidden" style={{ width: "100%", height: "100%", background: "var(--surface-inset)" }}>
        <span className="block rounded-full" style={{ width: `${pct * 100}%`, height: "100%", background: color, transition: "width .3s ease" }} />
      </span>
    </span>
  );
}

function heatColor(norm: number): string {
  const v = Math.max(-1, Math.min(1, norm));
  if (v >= 0.66) return "var(--heat-pos-3)";
  if (v >= 0.33) return "var(--heat-pos-2)";
  if (v > 0.05) return "var(--heat-pos-1)";
  if (v <= -0.66) return "var(--heat-neg-3)";
  if (v <= -0.33) return "var(--heat-neg-2)";
  if (v < -0.05) return "var(--heat-neg-1)";
  return "var(--heat-zero)";
}

export function HeatCell({ value, norm, className }: { value: ReactNode; norm: number; className?: string }) {
  return (
    <span className={"mono px-1.5 py-0.5 rounded-chip inline-block " + (className ?? "")} style={{ background: heatColor(norm) }}>
      {value}
    </span>
  );
}

export function RChip({ r, className }: { r: number | null | undefined; className?: string }) {
  const pos = (r ?? 0) >= 0;
  const color = r == null ? "var(--text-lo)" : pos ? "var(--long)" : "var(--short)";
  return (
    <span className={"mono text-dense px-1.5 py-0.5 rounded-chip inline-block " + (className ?? "")}
      style={{ color, background: `color-mix(in srgb, ${color} 14%, transparent)` }}>
      {fmtR(r)}
    </span>
  );
}

export function StatusDot({ status, label, pulse }: { status: "ok" | "warn" | "down"; label?: string; pulse?: boolean }) {
  const c = status === "ok" ? "var(--long)" : status === "warn" ? "var(--warn)" : "var(--short)";
  return (
    <span className="inline-flex items-center gap-1.5" title={label}>
      <span className={"inline-block rounded-full " + (pulse ? "alarm-pulse" : "")} style={{ width: 8, height: 8, background: c }} />
      {label && <span className="text-dense text-text-lo">{label}</span>}
    </span>
  );
}

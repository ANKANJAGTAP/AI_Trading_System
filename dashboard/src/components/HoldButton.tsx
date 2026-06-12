// Hold-to-confirm button (frontend_v2 §1.3) — critical actions resist accident.
import { useRef, useState } from "react";

export function HoldButton({ onConfirm, label, ms = 2000, danger, className }:
  { onConfirm: () => void; label: string; ms?: number; danger?: boolean; className?: string }) {
  const [progress, setProgress] = useState(0);
  const raf = useRef<number | undefined>(undefined);
  const startAt = useRef(0);

  function begin() {
    startAt.current = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - startAt.current) / ms);
      setProgress(p);
      if (p >= 1) {
        setProgress(0);
        onConfirm();
        return;
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
  }
  function cancel() {
    if (raf.current) cancelAnimationFrame(raf.current);
    setProgress(0);
  }

  const accent = danger ? "var(--short)" : "var(--brand)";
  return (
    <button
      onPointerDown={begin}
      onPointerUp={cancel}
      onPointerLeave={cancel}
      title={`Hold ${ms / 1000}s to confirm`}
      className={"relative overflow-hidden rounded-control border px-2 py-1 text-dense font-medium " + (className ?? "")}
      style={{ borderColor: "var(--line-strong)", color: danger ? "var(--short)" : "var(--text-hi)" }}
    >
      <span className="absolute inset-y-0 left-0" style={{ width: `${progress * 100}%`, background: accent, opacity: 0.28 }} />
      <span className="relative">{label}</span>
    </button>
  );
}

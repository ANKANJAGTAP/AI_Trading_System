// The Mode Frame (frontend_v2 §2.6A) — the single most important pixel in the app.
// A 3px inset viewport border keyed to mode; animates on flip.
import { useStore } from "@/store/store";

export function ModeFrame() {
  const mode = useStore((s) => s.mode);
  const color = mode === "live" ? "var(--mode-live)" : "var(--mode-sim)";
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-[55]"
      style={{ border: `3px solid ${color}`, transition: "border-color 400ms ease" }} />
  );
}

// Value-tick (frontend_v2 §2.5): a 180ms background flash on change, then fade.
import { useEffect, useRef, useState } from "react";

export function TickNum({ value, fmt, className }:
  { value: number | null | undefined; fmt: (v: number | null | undefined) => string; className?: string }) {
  const prev = useRef<number | null | undefined>(value);
  const [flash, setFlash] = useState("");

  useEffect(() => {
    if (value != null && prev.current != null && value !== prev.current) {
      setFlash(value > prev.current ? "tick-up" : "tick-down");
      const id = setTimeout(() => setFlash(""), 200);
      prev.current = value;
      return () => clearTimeout(id);
    }
    prev.current = value;
  }, [value]);

  return <span className={`rounded px-0.5 ${flash} ${className ?? ""}`}>{fmt(value)}</span>;
}

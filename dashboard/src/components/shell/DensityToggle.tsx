// Density mode cycle: comfortable -> compact -> ultra (frontend_v2 §2.3), persisted.
import { Rows3 } from "lucide-react";
import { useStore, type Density } from "@/store/store";

const ORDER: Density[] = ["comfortable", "compact", "ultra"];
const SHORT: Record<Density, string> = { comfortable: "CMF", compact: "CMP", ultra: "ULT" };

export function DensityToggle() {
  const density = useStore((s) => s.density);
  const setDensity = useStore((s) => s.setDensity);
  const next = () => setDensity(ORDER[(ORDER.indexOf(density) + 1) % ORDER.length]);
  return (
    <button onClick={next} title={`Density: ${density} (click to cycle)`}
      className="flex items-center gap-1 rounded-control border px-2 py-0.5 text-text-lo"
      style={{ borderColor: "var(--line-strong)" }}>
      <Rows3 size={12} />
      <span className="eyebrow">{SHORT[density]}</span>
    </button>
  );
}

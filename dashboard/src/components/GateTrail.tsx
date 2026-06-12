// The Gate Trail (frontend_v2 §2.6B) — the product's reasoning made legible. A signal's
// pipeline as a horizontal track of gate nodes; a reject halts the trail and dims
// downstream nodes; confidence + LLM veto render as the final nodes. With `animate`,
// nodes resolve left-to-right (120ms stagger) — key it by signal id to re-run on change.
import { motion } from "framer-motion";
import type { ReactNode } from "react";
import type { GateNode } from "@/lib/types";

const container = { hidden: {}, show: { transition: { staggerChildren: 0.12 } } };
const variant = { hidden: { opacity: 0, y: 5 }, show: { opacity: 1, y: 0, transition: { duration: 0.12 } } };

function Node({ label, color, dim, scoreFrac, sub }:
  { label: string; color: string; dim?: boolean; scoreFrac?: number; sub?: ReactNode }) {
  return (
    <div className="flex min-w-[70px] flex-col gap-1" style={{ opacity: dim ? 0.3 : 1 }}>
      <div className="flex items-center gap-1">
        <span className="inline-block rounded-full"
          style={{ width: 9, height: 9, background: scoreFrac != null ? color : color, border: `1.5px solid ${color}` }} />
        <span className="eyebrow truncate" title={label}>{label}</span>
      </div>
      {scoreFrac != null ? (
        <div className="h-1 overflow-hidden rounded-full" style={{ background: "var(--surface-inset)" }}>
          <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(1, scoreFrac)) * 100}%`, background: color }} />
        </div>
      ) : (
        <span className="text-micro text-text-faint">{sub}</span>
      )}
    </div>
  );
}

export function GateTrail({ gates, confidence, llm, animate = false }:
  { gates: GateNode[]; confidence?: number | null; llm?: { veto: boolean; sentiment?: string; reason?: string } | null; animate?: boolean }) {
  let halted = false;
  const nodes: { key: string; el: ReactNode }[] = [];
  (gates ?? []).forEach((g, i) => {
    const dim = halted;
    if (!g.pass) halted = true;
    const c = g.pass ? "var(--brand)" : "var(--short)";
    nodes.push({ key: "g" + i, el: <Node label={g.name} color={g.pass ? c : "var(--short)"} dim={dim} scoreFrac={g.score || 0} /> });
  });
  if (confidence != null) {
    nodes.push({ key: "conf", el: <Node label="conf" color="var(--info)" dim={halted} sub={<span className="mono text-dense text-text-hi">{confidence.toFixed(2)}</span>} /> });
  }
  if (llm) {
    nodes.push({ key: "llm", el: <Node label="LLM" color={llm.veto ? "var(--short)" : "var(--long)"} sub={llm.veto ? "VETO" : llm.sentiment ?? "ok"} /> });
  }
  return (
    <motion.div className="flex items-stretch gap-1.5 overflow-x-auto py-1"
      variants={container} initial={animate ? "hidden" : false} animate="show">
      {nodes.map((n) => <motion.div key={n.key} variants={variant}>{n.el}</motion.div>)}
    </motion.div>
  );
}

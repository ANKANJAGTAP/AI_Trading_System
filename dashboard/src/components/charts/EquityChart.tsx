// Compact equity / P&L curve (SVG, token-colored, zero baseline). Used on Command
// Center + Analytics; reads from the token layer so it stays cohesive in dark.
export function EquityChart({ data, height = 120, className }:
  { data: { ts: string; value: number }[]; height?: number; className?: string }) {
  if (!data || data.length < 2) {
    return (
      <div className={"flex items-center justify-center text-dense text-text-faint " + (className ?? "")} style={{ height }}>
        No curve yet — the engine is scanning.
      </div>
    );
  }
  const W = 600;
  const values = data.map((d) => d.value);
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const rng = max - min || 1;
  const y = (v: number) => height - ((v - min) / rng) * (height - 4) - 2;
  const x = (i: number) => (i / (data.length - 1)) * W;
  const zeroY = y(0);
  const last = values[values.length - 1];
  const color = last >= 0 ? "var(--long)" : "var(--short)";
  const line = data.map((d, i) => `${x(i).toFixed(1)},${y(d.value).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${height}`} width="100%" height={height} preserveAspectRatio="none" className={className}>
      <line x1={0} y1={zeroY} x2={W} y2={zeroY} stroke="var(--line-strong)" strokeWidth={1} strokeDasharray="3 3" />
      <polygon points={`0,${zeroY} ${line} ${W},${zeroY}`} fill={color} opacity={0.12} />
      <polyline points={line} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}

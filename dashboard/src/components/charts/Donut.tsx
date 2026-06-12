// Allocation donut — capital = idle cash + each sleeve's deployed (idle is a position).
export interface DonutSeg {
  label: string;
  value: number;
  color: string;
}

export function Donut({ data, size = 132, thickness = 18 }: { data: DonutSeg[]; size?: number; thickness?: number }) {
  const total = data.reduce((s, d) => s + Math.max(0, d.value), 0) || 1;
  const r = (size - thickness) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circ = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <g transform={`rotate(-90 ${cx} ${cy})`}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--surface-inset)" strokeWidth={thickness} />
        {data.map((d, i) => {
          const len = (Math.max(0, d.value) / total) * circ;
          const el = (
            <circle key={i} cx={cx} cy={cy} r={r} fill="none" stroke={d.color} strokeWidth={thickness}
              strokeDasharray={`${len} ${circ - len}`} strokeDashoffset={-offset} />
          );
          offset += len;
          return el;
        })}
      </g>
    </svg>
  );
}

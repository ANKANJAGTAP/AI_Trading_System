// F0 placeholder screen. The shell, design system, data layer, and API are live;
// each screen's body is filled in its phase (F1-F8). Never shows fabricated data.
export function ScreenPlaceholder({ title, phase, note }: { title: string; phase: string; note?: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
      <span className="font-ui text-xl tracking-tight text-text-hi">{title}</span>
      <span className="max-w-md text-dense text-text-faint">
        {note ?? "The shell, tokens, real-time layer and backend API are live. This screen's content is built in"}
      </span>
      <span className="eyebrow text-brand">{phase}</span>
    </div>
  );
}

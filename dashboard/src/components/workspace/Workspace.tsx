// Workspace (frontend_v2 §4.0) — configurable multi-pane grid; drag/resize; saved
// layouts persisted to the backend (/api/layouts).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Save, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Responsive, WidthProvider, type Layout } from "react-grid-layout";
import { api } from "@/lib/api";
import { useStore } from "@/store/store";
import { PANELS, PANEL_TYPES } from "./panels";

const RGL = WidthProvider(Responsive);

interface WState {
  layout: Layout[];
  panels: Record<string, string>;
}

const DEFAULT: WState = {
  layout: [
    { i: "p1", x: 0, y: 0, w: 4, h: 3 },
    { i: "p2", x: 4, y: 0, w: 8, h: 3 },
    { i: "p3", x: 0, y: 3, w: 6, h: 4 },
    { i: "p4", x: 6, y: 3, w: 6, h: 4 },
  ],
  panels: { p1: "pnl", p2: "market", p3: "positions", p4: "signals" },
};

export function Workspace() {
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();
  const layouts = useQuery({ queryKey: ["layouts"], queryFn: api.layouts });
  const [state, setState] = useState<WState>(DEFAULT);

  useEffect(() => {
    const saved = layouts.data?.find((l: any) => l.name === "default");
    if (saved?.layout?.layout) setState(saved.layout);
  }, [layouts.data]);

  const save = useMutation({
    mutationFn: () => api.putLayout("default", state),
    onSuccess: () => {
      toast("Workspace layout saved", "info");
      qc.invalidateQueries({ queryKey: ["layouts"] });
    },
    onError: (e: any) => toast(String(e.message), "short"),
  });

  const addPanel = (type: string) => {
    const id = "p" + Date.now();
    setState((s) => ({
      layout: [...s.layout, { i: id, x: 0, y: Infinity, w: 4, h: 3 }],
      panels: { ...s.panels, [id]: type },
    }));
  };
  const removePanel = (id: string) =>
    setState((s) => ({
      layout: s.layout.filter((l) => l.i !== id),
      panels: Object.fromEntries(Object.entries(s.panels).filter(([k]) => k !== id)),
    }));

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b px-3 py-1.5">
        <span className="eyebrow">Workspace</span>
        <div className="flex-1" />
        <div className="flex items-center gap-1">
          {PANEL_TYPES.map((t) => (
            <button key={t} onClick={() => addPanel(t)} title={`Add ${PANELS[t].title}`}
              className="flex items-center gap-0.5 rounded-control border px-1.5 py-0.5 text-dense text-text-lo hover:text-text-hi">
              <Plus size={11} /> {t}
            </button>
          ))}
        </div>
        <button onClick={() => save.mutate()} className="flex items-center gap-1 rounded-control border px-2 py-0.5 text-dense">
          <Save size={12} /> Save
        </button>
      </div>
      <div className="flex-1 overflow-auto p-2">
        <RGL className="layout" layouts={{ lg: state.layout }} breakpoints={{ lg: 0 }} cols={{ lg: 12 }}
          rowHeight={64} margin={[8, 8]} draggableHandle=".panel-drag"
          onLayoutChange={(l: Layout[]) => setState((s) => ({ ...s, layout: l }))}>
          {state.layout.map((item) => {
            const def = PANELS[state.panels[item.i]];
            return (
              <div key={item.i} className="flex flex-col overflow-hidden rounded-panel border bg-surface">
                <div className="panel-drag flex cursor-move items-center justify-between border-b bg-surface-raised px-2 py-1">
                  <span className="eyebrow">{def?.title ?? state.panels[item.i]}</span>
                  <button onClick={() => removePanel(item.i)} className="text-text-faint hover:text-text-hi" title="Remove panel">
                    <X size={12} />
                  </button>
                </div>
                <div className="flex-1 overflow-auto">{def ? def.render() : null}</div>
              </div>
            );
          })}
        </RGL>
      </div>
    </div>
  );
}

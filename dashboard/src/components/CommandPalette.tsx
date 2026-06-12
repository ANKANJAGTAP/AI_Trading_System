// Command Palette (⌘K) — fuzzy navigation + a few safe actions. The keyboard backbone.
import { Command } from "cmdk";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { NAV } from "@/nav";
import { useStore, type Density } from "@/store/store";

const NEXT_DENSITY: Record<Density, Density> = { comfortable: "compact", compact: "ultra", ultra: "comfortable" };

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const nav = useNavigate();
  const density = useStore((s) => s.density);
  const setDensity = useStore((s) => s.setDensity);
  const toast = useStore((s) => s.toast);
  const go = (path: string) => {
    nav(path);
    onOpenChange(false);
  };
  return (
    <Command.Dialog open={open} onOpenChange={onOpenChange} label="Command palette">
      <Command.Input placeholder="Jump to a screen or run a command…" />
      <Command.List>
        <Command.Empty>No results.</Command.Empty>
        <Command.Group heading="Navigate">
          {NAV.map((n) => (
            <Command.Item key={n.path} value={`go ${n.label}`} onSelect={() => go(n.path)}>
              <n.icon size={14} /> {n.label}
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading="Actions">
          <Command.Item value="cycle density" onSelect={() => setDensity(NEXT_DENSITY[density])}>
            Cycle density (current: {density})
          </Command.Item>
          <Command.Item value="pause engine" onSelect={async () => {
            onOpenChange(false);
            try {
              await api.pause(true);
              toast("Engine paused — new entries blocked", "warn");
            } catch (e: any) {
              toast(String(e.message), "short");
            }
          }}>
            Pause engine (new entries)
          </Command.Item>
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}

// Toast system — speaks in the interface voice; colored by semantic kind.
import { AnimatePresence, motion } from "framer-motion";
import { useStore } from "@/store/store";

const color = (k: string) =>
  k === "short" ? "var(--short)" : k === "long" ? "var(--long)" : k === "warn" ? "var(--warn)" : "var(--brand)";

export function Toaster() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismissToast);
  return (
    <div className="fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2" aria-live="polite">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.button
            key={t.id}
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 24 }}
            onClick={() => dismiss(t.id)}
            className="flex items-start gap-2 rounded-panel border bg-surface-raised px-3 py-2 text-left text-dense shadow-lg"
            style={{ borderLeftColor: color(t.kind), borderLeftWidth: 3 }}
            role="status"
          >
            <span className="flex-1 text-text-hi">{t.title}</span>
          </motion.button>
        ))}
      </AnimatePresence>
    </div>
  );
}

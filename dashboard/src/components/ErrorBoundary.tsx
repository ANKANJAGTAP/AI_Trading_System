// Error boundary (frontend_v2 §8 F9 hardening) — a crashing screen shows a recoverable
// fallback instead of blanking the whole console. Keyed by route to reset on navigation.
import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error) {
    console.error("[aegis] screen error", error);
  }
  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
          <span className="font-ui text-text-hi">This panel hit an error.</span>
          <span className="max-w-md text-dense text-text-faint">{this.state.error.message}</span>
          <button onClick={() => this.setState({ error: null })} className="rounded-control border px-3 py-1 text-dense">retry</button>
        </div>
      );
    }
    return this.props.children;
  }
}

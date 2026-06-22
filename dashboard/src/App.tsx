import { useEffect, useState } from "react";
import { Outlet, Route, Routes, useLocation, useParams } from "react-router-dom";
import { CommandPalette } from "@/components/CommandPalette";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { LoginGate } from "@/components/LoginGate";
import { Toaster } from "@/components/Toaster";
import { Inspector } from "@/components/shell/Inspector";
import { ModeFrame } from "@/components/shell/ModeFrame";
import { Rail } from "@/components/shell/Rail";
import { StatusBar } from "@/components/shell/StatusBar";
import { TickerTape } from "@/components/shell/TickerTape";
import { Workspace } from "@/components/workspace/Workspace";
import { connectWs } from "@/lib/ws";
import { SCREENS } from "@/screenRegistry";
import { Analytics } from "@/screens/Analytics";
import { Audit } from "@/screens/Audit";
import { Backtest } from "@/screens/Backtest";
import { Charts } from "@/screens/Charts";
import { CommandCenter } from "@/screens/CommandCenter";
import { Controls } from "@/screens/Controls";
import { FnoResearch } from "@/screens/FnoResearch";
import { PreLiveReadiness } from "@/screens/PreLiveReadiness";
import { Market } from "@/screens/Market";
import { OptionChain } from "@/screens/OptionChain";
import { Positions } from "@/screens/Positions";
import { Risk } from "@/screens/Risk";
import { Settings } from "@/screens/Settings";
import { Signals } from "@/screens/Signals";
import { Sleeves } from "@/screens/Sleeves";
import { StructureLab } from "@/screens/StructureLab";
import { Watch } from "@/screens/Watch";
import { useStore } from "@/store/store";

function Shell() {
  const [palette, setPalette] = useState(false);
  const loc = useLocation();

  useEffect(() => {
    document.documentElement.dataset.density = useStore.getState().density;
    connectWs();
  }, []);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((o) => !o);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <ModeFrame />
      <StatusBar onOpenPalette={() => setPalette(true)} />
      <TickerTape />
      <div className="flex min-h-0 flex-1">
        <Rail />
        <main className="min-w-0 flex-1 overflow-hidden">
          <ErrorBoundary key={loc.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
        <Inspector />
      </div>
      <CommandPalette open={palette} onOpenChange={setPalette} />
      <Toaster />
    </div>
  );
}

// Detached single-screen window for multi-monitor (window.open("/popout/<screen>")).
function Popout() {
  const { screen } = useParams();
  const Screen = screen ? SCREENS[screen] : undefined;
  useEffect(() => {
    document.documentElement.dataset.density = useStore.getState().density;
    connectWs();
  }, []);
  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <ModeFrame />
      <div className="flex h-7 items-center gap-2 border-b bg-surface px-3 text-dense">
        <span className="eyebrow">Aegis · detached</span>
        <span className="text-text-faint">·</span>
        <span className="text-text-lo">{screen}</span>
      </div>
      <div className="min-h-0 flex-1">
        <ErrorBoundary key={screen}>
          {Screen ? <Screen /> : <div className="p-8 text-center text-dense text-text-faint">Unknown screen: {screen}</div>}
        </ErrorBoundary>
      </div>
      <Inspector />
      <Toaster />
    </div>
  );
}

export default function App() {
  return (
    <LoginGate>
      <Routes>
        <Route path="/watch" element={<Watch />} />
        <Route path="/popout/:screen" element={<Popout />} />
        <Route element={<Shell />}>
          <Route index element={<CommandCenter />} />
          <Route path="workspace" element={<Workspace />} />
          <Route path="market" element={<Market />} />
          <Route path="charts" element={<Charts />} />
          <Route path="positions" element={<Positions />} />
          <Route path="signals" element={<Signals />} />
          <Route path="optionchain" element={<OptionChain />} />
          <Route path="sleeves" element={<Sleeves />} />
          <Route path="risk" element={<Risk />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="backtest" element={<Backtest />} />
          <Route path="structure" element={<StructureLab />} />
          <Route path="fno-research" element={<FnoResearch />} />
          <Route path="prelive" element={<PreLiveReadiness />} />
          <Route path="audit" element={<Audit />} />
          <Route path="controls" element={<Controls />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </LoginGate>
  );
}

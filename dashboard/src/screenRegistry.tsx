// name -> screen component. Powers the pop-out windows (/popout/:screen) and keeps a
// single source for which screens exist.
import type { ComponentType } from "react";
import { Workspace } from "@/components/workspace/Workspace";
import { Analytics } from "@/screens/Analytics";
import { Audit } from "@/screens/Audit";
import { Backtest } from "@/screens/Backtest";
import { Charts } from "@/screens/Charts";
import { CommandCenter } from "@/screens/CommandCenter";
import { Controls } from "@/screens/Controls";
import { Market } from "@/screens/Market";
import { OptionChain } from "@/screens/OptionChain";
import { Positions } from "@/screens/Positions";
import { Risk } from "@/screens/Risk";
import { Settings } from "@/screens/Settings";
import { Signals } from "@/screens/Signals";
import { Sleeves } from "@/screens/Sleeves";

export const SCREENS: Record<string, ComponentType> = {
  "command-center": CommandCenter,
  workspace: Workspace,
  market: Market,
  charts: Charts,
  positions: Positions,
  signals: Signals,
  optionchain: OptionChain,
  sleeves: Sleeves,
  risk: Risk,
  analytics: Analytics,
  backtest: Backtest,
  audit: Audit,
  controls: Controls,
  settings: Settings,
};

// pathname ("/", "/market", ...) -> registry key, for "pop out current view".
export function screenKeyForPath(pathname: string): string {
  if (pathname === "/" || pathname === "") return "command-center";
  return pathname.replace(/^\//, "").split("/")[0];
}

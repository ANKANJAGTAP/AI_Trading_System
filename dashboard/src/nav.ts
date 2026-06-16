// Screen registry — single source for the Rail, Command Palette, and routing.
import {
  Briefcase, CandlestickChart, Database, FlaskConical, Gauge, Layers, LayoutGrid, PieChart, Radar,
  ScrollText, Settings, ShieldAlert, ShieldCheck, SlidersHorizontal, TrendingUp, Workflow,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
}

export const NAV: NavItem[] = [
  { path: "/workspace", label: "Workspace", icon: LayoutGrid },
  { path: "/", label: "Command Center", icon: Gauge },
  { path: "/market", label: "Market", icon: Radar },
  { path: "/charts", label: "Charts", icon: CandlestickChart },
  { path: "/positions", label: "Positions", icon: Briefcase },
  { path: "/signals", label: "Signals", icon: Workflow },
  { path: "/optionchain", label: "Option Chain", icon: Layers },
  { path: "/sleeves", label: "Sleeves", icon: PieChart },
  { path: "/risk", label: "Risk", icon: ShieldAlert },
  { path: "/analytics", label: "Analytics", icon: TrendingUp },
  { path: "/backtest", label: "Backtest", icon: FlaskConical },
  { path: "/fno-research", label: "F&O Research", icon: Database },
  { path: "/prelive", label: "Go-Live", icon: ShieldCheck },
  { path: "/audit", label: "Audit", icon: ScrollText },
  { path: "/controls", label: "Controls", icon: SlidersHorizontal },
  { path: "/settings", label: "Settings", icon: Settings },
];

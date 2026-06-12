// Left rail — icon+label nav in operator-priority order, collapsible to icons.
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useState } from "react";
import { NavLink } from "react-router-dom";
import { NAV } from "@/nav";

export function Rail() {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <nav
      className="flex h-full flex-col border-r bg-surface"
      style={{ width: collapsed ? 48 : 184, transition: "width .15s ease" }}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <span className="font-ui font-semibold tracking-tight text-brand">{collapsed ? "Æ" : "AEGIS"}</span>
      </div>
      <div className="flex-1 overflow-y-auto py-1">
        {NAV.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              className={({ isActive }) =>
                "flex items-center gap-2.5 px-3 py-1.5 text-dense " +
                (isActive ? "text-text-hi" : "text-text-lo hover:text-text-hi")
              }
              style={({ isActive }) => (isActive ? { boxShadow: "inset 2px 0 0 var(--brand)", background: "var(--surface-raised)" } : {})}
              title={item.label}
            >
              <Icon size={15} className="shrink-0" />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </NavLink>
          );
        })}
      </div>
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex items-center justify-center border-t py-2 text-text-faint hover:text-text-lo"
        title={collapsed ? "Expand" : "Collapse"}
      >
        {collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
      </button>
    </nav>
  );
}

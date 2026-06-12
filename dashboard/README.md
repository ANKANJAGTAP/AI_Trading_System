# Dashboard (operator console)

React (Vite) + Recharts operator console. **Built in Phase 6.**

The backend exposes all dashboard data via FastAPI (REST + WebSocket push):
capital/sleeve utilisation, open positions with live PnL & R-at-risk, today's
signals with full gate trails, PnL vs kill-switch line, a prominent
**SIMULATED / LIVE** mode indicator, and controls (pause/resume, flatten-all,
per-sleeve toggles, mode flip with confirm, kill-switch reset).

Phase 0 ships only the `/health` endpoint on the API.

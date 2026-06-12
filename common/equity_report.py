"""Running equity curve + 1-month projection, rendered as text and HTML.

Single source of truth for the daily equity report. Starts from a base capital
(default: config risk.paper_capital = ₹10L) and rolls each trading day's *realized*
P&L into a running balance — profit added, loss subtracted, compounding forward —
then projects ~1 month ahead from the average daily P&L seen so far.

Consumed by:
  - scripts/equity_curve.py  (CLI: prints the text form)
  - engine/main.py _eod_summary  (emails text + HTML every day after close)

Realized P&L (closed positions, bucketed by closed_at in IST) is what actually
moves the account; still-open positions are shown separately as live MTM. The
projection is a naive linear extrapolation (future days = average of past days):
a planning aid, not a forecast — it gets meaningful after a couple of weeks.
"""
from __future__ import annotations

from dataclasses import dataclass

from common.db import fetch, fetchrow
from config.loader import get_config

# NSE trades ~21 sessions per calendar month (5-day weeks, minus holidays).
TRADING_DAYS_PER_MONTH = 21
CAL_DAYS_PER_TRADING_DAY = 7 / 5  # rough trading-day -> calendar-day conversion
DEFAULT_CAPITAL = 1_000_000.0     # ₹10L paper notional, used if config is 0


@dataclass
class EquityReport:
    subject: str
    text: str
    html: str
    start_capital: float
    balance: float        # realized running balance (start + sum of daily realized)
    equity_now: float     # balance + live open-position MTM
    open_mtm: float
    open_n: int
    n_days: int           # trading days with closed trades observed
    avg_daily: float      # average realized P&L per observed trading day
    horizon_days: int
    projected: float      # projected balance after `horizon_days`


async def build_equity_report(
    start_capital: float | None = None,
    horizon_days: int = TRADING_DAYS_PER_MONTH,
) -> EquityReport:
    cfg = get_config()
    if start_capital is None:
        start_capital = float(getattr(cfg.risk, "paper_capital", 0) or 0)
    if start_capital <= 0:
        start_capital = DEFAULT_CAPITAL

    # Realized P&L per IST trading day (only closed positions move the account).
    # TRADE-level: a multi-leg structure's legs share one correlation_id and count as
    # ONE trade (one W or L on its combined P&L), booked on its last leg's close day —
    # leg-level counting overstated activity and distorted the W/L read.
    rows = await fetch(
        "SELECT d, COUNT(*) AS n, SUM(pnl) AS pnl, "
        "SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins, "
        "SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses FROM ("
        "  SELECT (MAX(closed_at) AT TIME ZONE 'Asia/Kolkata')::date AS d, "
        "         SUM(COALESCE(realized_pnl, 0)) AS pnl "
        "  FROM positions WHERE status = 'closed' AND closed_at IS NOT NULL "
        "  GROUP BY COALESCE(correlation_id::text, id::text)"
        ") t GROUP BY d ORDER BY d")

    # Live mark-to-market on still-open positions (not yet realized into the account).
    openrow = await fetchrow(
        "SELECT COALESCE(SUM(unrealized_pnl), 0) AS up, COUNT(*) AS n "
        "FROM positions WHERE status <> 'closed'")
    open_mtm = float(openrow["up"]) if openrow else 0.0
    open_n = int(openrow["n"]) if openrow else 0

    # ---- Roll the running balance, one trading day at a time ------------------
    balance = start_capital
    daily: list[dict] = []
    for r in rows:
        day_pnl = float(r["pnl"])
        balance += day_pnl
        daily.append({
            "date": str(r["d"]),
            "n": int(r["n"]),
            "wins": int(r["wins"]),
            "losses": int(r["losses"]),
            "pnl": day_pnl,
            "balance": balance,
            "vs": (balance - start_capital) / start_capital * 100.0,
        })

    n_days = len(daily)
    realized_total = balance - start_capital
    avg_daily = (realized_total / n_days) if n_days else 0.0
    win_days = sum(1 for d in daily if d["pnl"] > 0)
    loss_days = sum(1 for d in daily if d["pnl"] < 0)
    equity_now = balance + open_mtm
    projected = balance + avg_daily * horizon_days
    pct_vs_start = realized_total / start_capital * 100.0

    # ---- Projection verdict (shared by text + HTML) ---------------------------
    if n_days == 0:
        verdict = ("No closed trades yet — nothing has been added or subtracted. "
                   "A projection needs a few closed trading days of history.")
    elif avg_daily > 0:
        monthly = avg_daily * TRADING_DAYS_PER_MONTH
        verdict = (f"Trend is POSITIVE (~Rs {monthly:+,.0f}/month). On the current "
                   "average the account keeps growing — it does not trend to zero.")
    elif avg_daily < 0:
        days_to_zero = balance / (-avg_daily)
        cal_days = days_to_zero * CAL_DAYS_PER_TRADING_DAY
        verdict = (f"Trend is NEGATIVE (~Rs {avg_daily*TRADING_DAYS_PER_MONTH:+,.0f}/month). "
                   f"At this average the balance reaches ZERO in ~{round(days_to_zero)} "
                   f"trading days (~{round(cal_days)} calendar days, "
                   f"~{days_to_zero/TRADING_DAYS_PER_MONTH:.1f} months).")
    else:
        verdict = "Trend is flat (avg ≈ 0): balance holds near the starting amount."

    subject = (f"Equity report {daily[-1]['date'] if daily else 'today'}: "
               f"Rs {balance:,.0f} ({pct_vs_start:+.2f}% vs start)")

    text = _render_text(start_capital, daily, balance, realized_total, pct_vs_start,
                        open_n, open_mtm, equity_now, n_days, win_days, loss_days,
                        avg_daily, horizon_days, projected, verdict)
    html = _render_html(start_capital, daily, balance, realized_total, pct_vs_start,
                        open_n, open_mtm, equity_now, n_days, win_days, loss_days,
                        avg_daily, horizon_days, projected, verdict)

    return EquityReport(
        subject=subject, text=text, html=html, start_capital=start_capital,
        balance=balance, equity_now=equity_now, open_mtm=open_mtm, open_n=open_n,
        n_days=n_days, avg_daily=avg_daily, horizon_days=horizon_days, projected=projected,
    )


def _render_text(start_cap, daily, balance, realized_total, pct, open_n, open_mtm,
                 equity_now, n_days, win_days, loss_days, avg_daily, horizon,
                 projected, verdict) -> str:
    L = ["================= EQUITY CURVE & PROJECTION =================",
         f"Starting capital: Rs {start_cap:,.0f}",
         "------------------------------------------------------------"]
    if not daily:
        L += [verdict,
              f"Open positions: {open_n}   live MTM: Rs {open_mtm:,.0f}",
              f"Current equity (incl. open MTM): Rs {equity_now:,.0f}",
              "============================================================"]
        return "\n".join(L)

    L.append(f"{'Date':12} {'trades':>6} {'W/L':>7} {'day P&L':>14} {'balance':>16} {'vs start':>9}")
    L.append("-" * 72)
    for d in daily:
        wl = f"{d['wins']}/{d['losses']}"
        L.append(f"{d['date']:12} {d['n']:>6} {wl:>7} "
                 f"Rs {d['pnl']:>+11,.0f} Rs {d['balance']:>13,.0f} {d['vs']:>+7.1f}%")
    L += [
        "-" * 72,
        f"Realized balance:        Rs {balance:,.0f}  ({pct:+.2f}% vs start)",
        f"Open positions:          {open_n}   live MTM: Rs {open_mtm:,.0f}",
        f"Equity incl. open MTM:   Rs {equity_now:,.0f}",
        "------------------------------------------------------------",
        f"Trading days observed:   {n_days}   (up days {win_days} / down days {loss_days})",
        f"Average daily P&L:       Rs {avg_daily:+,.0f} / day",
        "------------------------------------------------------------",
        f"PROJECTION (naive: future days = avg of past {n_days} days)",
        f"  After {horizon} trading days (~1 month): Rs {projected:,.0f}  "
        f"({(projected-start_cap)/start_cap*100:+.1f}% vs start)",
        f"  {verdict}",
        "  NOTE: linear extrapolation only — real results vary; the daily",
        "  kill-switch caps any single day's loss. Accuracy improves with more days.",
        "============================================================",
    ]
    return "\n".join(L)


def _render_html(start_cap, daily, balance, realized_total, pct, open_n, open_mtm,
                 equity_now, n_days, win_days, loss_days, avg_daily, horizon,
                 projected, verdict) -> str:
    def money(v):
        return f"Rs&nbsp;{v:,.0f}"

    def color(v):
        return "#137333" if v > 0 else ("#c5221f" if v < 0 else "#5f6368")

    head_pct_color = color(realized_total)
    rows_html = ""
    for d in daily:
        rows_html += (
            "<tr>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{d['date']}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right'>{d['n']}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right'>{d['wins']}/{d['losses']}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:{color(d['pnl'])}'>{d['pnl']:+,.0f}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right;font-weight:600'>{money(d['balance'])}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:{color(d['vs'])}'>{d['vs']:+.1f}%</td>"
            "</tr>")

    if not daily:
        table = f"<p style='color:#5f6368'>{verdict}</p>"
    else:
        table = (
            "<table style='border-collapse:collapse;width:100%;font-size:13px;"
            "font-family:Menlo,Consolas,monospace'>"
            "<thead><tr style='background:#f1f3f4;text-align:right'>"
            "<th style='padding:8px 10px;text-align:left'>Date</th>"
            "<th style='padding:8px 10px'>Trades</th>"
            "<th style='padding:8px 10px'>W/L</th>"
            "<th style='padding:8px 10px'>Day P&amp;L</th>"
            "<th style='padding:8px 10px'>Balance</th>"
            "<th style='padding:8px 10px'>vs start</th>"
            f"</tr></thead><tbody>{rows_html}</tbody></table>")

    proj_pct = ((projected - start_cap) / start_cap * 100.0) if start_cap else 0.0
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#202124;max-width:680px">
  <h2 style="margin:0 0 4px">📈 Daily Equity Report</h2>
  <p style="margin:0 0 16px;color:#5f6368">
    Starting capital <b>{money(start_cap)}</b> · each day's profit/loss added to the main amount, compounding.
  </p>
  <table style="border-collapse:collapse;margin-bottom:16px">
    <tr>
      <td style="padding:10px 16px;background:#f8f9fa;border-radius:8px 0 0 8px">
        <div style="font-size:12px;color:#5f6368">Current balance</div>
        <div style="font-size:22px;font-weight:700">{money(balance)}</div>
        <div style="font-size:13px;color:{head_pct_color}">{pct:+.2f}% vs start</div>
      </td>
      <td style="padding:10px 16px;background:#f8f9fa">
        <div style="font-size:12px;color:#5f6368">Open positions MTM</div>
        <div style="font-size:22px;font-weight:700">{open_mtm:+,.0f}</div>
        <div style="font-size:13px;color:#5f6368">{open_n} open · equity {money(equity_now)}</div>
      </td>
      <td style="padding:10px 16px;background:#f8f9fa;border-radius:0 8px 8px 0">
        <div style="font-size:12px;color:#5f6368">Avg / day · {n_days} day(s)</div>
        <div style="font-size:22px;font-weight:700;color:{color(avg_daily)}">{avg_daily:+,.0f}</div>
        <div style="font-size:13px;color:#5f6368">up {win_days} / down {loss_days}</div>
      </td>
    </tr>
  </table>
  {table}
  <div style="margin-top:16px;padding:12px 16px;background:#fef7e0;border-left:4px solid #f9ab00;border-radius:4px">
    <div style="font-weight:600;margin-bottom:4px">1-month projection (~{horizon} trading days)</div>
    <div style="font-size:18px;font-weight:700">{money(projected)} <span style="font-size:13px;font-weight:400;color:#5f6368">({proj_pct:+.1f}% vs start)</span></div>
    <div style="margin-top:6px;color:#5f6368;font-size:13px">{verdict}</div>
  </div>
  <p style="margin-top:14px;color:#9aa0a6;font-size:12px">
    Naive linear extrapolation (future days = average of past days) — a planning aid, not a forecast.
    Realized P&amp;L (closed positions) moves the account; open positions shown separately as live MTM.
    The daily kill-switch caps any single day's loss. — AI Trading System
  </p>
</div>"""

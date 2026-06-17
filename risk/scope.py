"""Mode + account scoping for the position book (P1#8).

Pure helpers: derive the active scope from a RuntimeModeState and build the SQL
filter so every risk / P&L read sees only the ACTIVE namespace's rows — paper and
live positions never mix into one sizing, kill-switch, or capital calculation.
"""
from __future__ import annotations

PAPER = "simulated_fill"
LIVE = "live"


def position_scope(state) -> dict:
    """{'mode': namespace, 'account_id': id|None} from a RuntimeModeState.
    Fail-closed: a missing/garbled state scopes to paper, never to all rows."""
    ns = getattr(state, "position_namespace", None) or PAPER
    acct = getattr(state, "broker_account_id", None)
    if ns != LIVE and not acct:
        acct = "paper"
    return {"mode": ns, "account_id": acct}


def where_clause(scope: dict, start_idx: int = 1) -> tuple[str, list]:
    """(sql_fragment, args) restricting `positions` to a scope. Always filters by
    mode; filters by account_id only when it's a real (non-paper) account, since
    legacy/paper rows may carry a null account_id."""
    conds: list[str] = []
    args: list = []
    i = start_idx
    conds.append(f"mode = ${i}")
    args.append(scope.get("mode") or PAPER)
    i += 1
    acct = scope.get("account_id")
    if acct and acct != "paper":
        conds.append(f"account_id = ${i}")
        args.append(acct)
        i += 1
    return " AND ".join(conds), args

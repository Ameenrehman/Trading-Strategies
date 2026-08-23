"""
The one definition of paper-portfolio state.

Why this module exists
----------------------
`generate_orders.py` and `paper_broker.py` each grew their own reader and
writer for `live/positions.json`, and the two schemas disagreed:

  generate_orders wrote  {as_of, capital, holdings}          — no cash
  paper_broker    wrote  {as_of, capital, cash, holdings}

Both failure directions were live:

  * paper_broker reading a generate_orders file found no "cash" key, fell back
    to `capital`, and handed itself a fresh Rs.10,00,000 of buying power on top
    of an already-invested book.
  * generate_orders reading a paper_broker file ignored "cash" entirely and
    hardcoded 0 whenever holdings existed, so proceeds from every sell were
    stranded and the book bled into dead cash at each rebalance.

Neither script was wrong on its own. The schema was, because it was written
twice. It is written once here.

Deliberately free of network imports so `generate_orders.py` still runs with no
credentials and no SmartApi package installed.
"""

import json
from pathlib import Path

LIVE_DIR = Path(__file__).parent
POSITIONS_FILE = LIVE_DIR / "positions.json"
LEDGER_FILE = LIVE_DIR / "paper_ledger.csv"

DEFAULT_CAPITAL = 1_000_000.0

#: Every writer emits exactly these keys.
POSITION_KEYS = ("as_of", "capital", "cash", "holdings", "last_updated")


def blank_positions(capital: float = DEFAULT_CAPITAL) -> dict:
    """A fresh, uninvested book."""
    return {"as_of": None, "capital": float(capital), "cash": float(capital),
            "holdings": {}, "last_updated": None}


def load_positions(capital_default: float = DEFAULT_CAPITAL,
                   quiet: bool = False) -> dict:
    """
    Read `positions.json`, repairing anything an older writer left out.

    A file with holdings but no "cash" key predates the unified schema. Cash is
    assumed to be ZERO in that case, not `capital`: an invested book with an
    unrecorded cash balance is far likelier than an empty one, and guessing
    high would invent money the portfolio never had.
    """
    if not POSITIONS_FILE.exists():
        return blank_positions(capital_default)
    try:
        pos = json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        if not quiet:
            print(f"  [WARN] {POSITIONS_FILE.name} is unreadable — starting fresh.")
        return blank_positions(capital_default)

    pos.setdefault("capital", capital_default)
    pos.setdefault("holdings", {})
    pos.setdefault("as_of", None)
    pos.setdefault("last_updated", None)
    if "cash" not in pos:
        pos["cash"] = 0.0 if pos["holdings"] else float(pos["capital"])
        if not quiet:
            print(f"  [WARN] {POSITIONS_FILE.name} predates the unified schema "
                  f"(no 'cash' key).")
            print(f"         Assuming Rs.{pos['cash']:,.0f} cash. Edit the file "
                  f"if that is wrong.")
    pos["capital"] = float(pos["capital"])
    pos["cash"] = float(pos["cash"])
    pos["holdings"] = {k: int(v) for k, v in pos["holdings"].items() if int(v) > 0}
    return pos


def save_positions(pos: dict):
    """Write state with every canonical key present."""
    out = {k: pos.get(k) for k in POSITION_KEYS}
    out["capital"] = float(out.get("capital") or DEFAULT_CAPITAL)
    out["cash"] = round(float(out.get("cash") or 0.0), 2)
    out["holdings"] = {k: int(v) for k, v in (out.get("holdings") or {}).items()
                       if int(v) > 0}
    for extra in ("_note",):
        if extra in pos:
            out[extra] = pos[extra]
    POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    POSITIONS_FILE.write_text(json.dumps(out, indent=2), encoding="utf-8")

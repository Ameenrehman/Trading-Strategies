"""
Monthly-rebalance portfolio backtester for delivery (CNC) strategies.

Why this exists: Backtesting.py is single-instrument. Cross-sectional ranking
across 200 names cannot be expressed in it, so the intraday tooling
(run_backtest.py, verify_fixes.py, test_gap_rvol.py, validate.py) does not
carry over. This is deliberately a small, explicit loop rather than vectorbt —
the entire point of this phase is a cost model we trust, and vectorbt was
already deferred once in Phase 1 for unverified SL/TP/EOD behaviour.

What it models
--------------
- Equal-weight positions in whole shares, rebalanced on a schedule.
- Costs charged per leg via backtest.costs.delivery_one_way_cost, which places
  STT (both legs), stamp duty (buy only) and DP charges (sell only) correctly.
  Charging a symmetric half round-trip would get all three wrong.
- Cash drag when fewer names qualify than n_positions — that is a real effect
  of the trend filter and must not be silently ignored.
- Optional daily-checked disaster stop and daily trend exit, so the exit rules
  discussed in strategies/momentum_xs.py can be tested rather than assumed.

What it does NOT model
----------------------
- Dividends. Returns are price-only, which understates every strategy AND the
  benchmark roughly equally, so comparisons stay fair. Stated in results.
- Intraday fills. Everything transacts at the rebalance date's close.
- Corporate actions beyond whatever the data feed already adjusts for. The
  fetcher's audit is what catches unadjusted splits.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.costs import delivery_one_way_cost, SLIPPAGE_PER_LEG

TRADING_DAYS = 252


def rebalance_dates(index: pd.DatetimeIndex, freq: str = "ME") -> list:
    """
    Dates on which the strategy re-ranks and may trade.

      'D'  - every trading day
      'W'  - weekly (last trading day of each week)
      'ME' - month-end   (default)
      'QE' - quarter-end

    Rebalance FREQUENCY is not the same thing as turnover, and it is turnover
    that costs money. Checking daily only trades more if the selection actually
    changes daily — a 12-month momentum score moves slowly, so most of the churn
    from frequent checking comes from names oscillating across the top-N
    boundary. `exit_rank_buffer` in MomentumConfig is the fix for that, not a
    slower calendar. Frequent checking with a buffer can give faster exits at
    similar turnover, which is why the frequency sweep in test_momentum.py
    reports turnover and cost drag next to returns.
    """
    if freq.upper() in ("D", "DAILY"):
        return list(index)
    s = pd.Series(index, index=index)
    return list(s.resample(freq).last().dropna())


def run_portfolio(closes: pd.DataFrame,
                  signal_fn,
                  initial_capital: float = 1_000_000.0,
                  rebalance: str = "ME",
                  start=None,
                  end=None,
                  slippage_per_leg: float = SLIPPAGE_PER_LEG,
                  charge_costs: bool = True,
                  disaster_stop_pct: float = 0.0,
                  trend_exit_fn=None,
                  weight_band: float = 0.0,
                  verbose: bool = False) -> dict:
    """
    Run one strategy.

    Parameters
    ----------
    closes : DataFrame of daily closes, DatetimeIndex, one column per symbol.
    signal_fn : (closes, asof, held) -> list[str] of symbols to hold.
    disaster_stop_pct : if > 0, liquidate a holding intra-period once it is
        this far below its entry price (checked daily on the close).
    trend_exit_fn : optional (closes, asof) -> Series[bool]; any held name that
        is False is liquidated that day rather than waiting for the rebalance.
    weight_band : 0 (default) lets existing positions drift — only entries and
        exits are traded. A value like 0.5 rebalances any position that has
        drifted more than 50% away from its equal-weight target. Non-zero
        values increase turnover, and turnover is the dominant cost driver.

    Returns a dict with the equity curve, per-rebalance turnover, trade log,
    cost total, and summary stats.
    """
    closes = closes.sort_index()
    if start is not None:
        closes = closes.loc[pd.Timestamp(start):]
    if end is not None:
        closes = closes.loc[:pd.Timestamp(end)]

    dates = closes.index
    rebals = set(rebalance_dates(dates, rebalance))

    cash = float(initial_capital)
    shares = {}            # symbol -> whole shares held
    entry_px = {}          # symbol -> entry price, for the disaster stop
    equity_curve = []
    turnovers = []
    trades = []
    total_costs = 0.0

    def portfolio_value(px_row):
        v = cash
        for sym, qty in shares.items():
            p = px_row.get(sym, np.nan)
            if np.isfinite(p):
                v += qty * p
        return v

    def sell(sym, price, date, reason):
        nonlocal cash, total_costs
        qty = shares.pop(sym, 0)
        entry_px.pop(sym, None)
        if qty <= 0 or not np.isfinite(price):
            return 0.0
        proceeds = qty * price
        cost = delivery_one_way_cost(proceeds, "sell", slippage_per_leg) if charge_costs else 0.0
        cash += proceeds - cost
        total_costs += cost
        trades.append({"date": date, "symbol": sym, "side": "sell", "qty": qty,
                       "price": price, "value": proceeds, "cost": cost, "reason": reason})
        return proceeds

    def buy(sym, price, target_value, date):
        nonlocal cash, total_costs
        if not np.isfinite(price) or price <= 0 or target_value <= 0:
            return 0.0
        qty = int(target_value // price)
        if qty < 1:
            return 0.0
        notional = qty * price
        cost = delivery_one_way_cost(notional, "buy", slippage_per_leg) if charge_costs else 0.0
        while qty >= 1 and notional + cost > cash:
            qty -= 1
            if qty < 1:
                return 0.0
            notional = qty * price
            cost = delivery_one_way_cost(notional, "buy", slippage_per_leg) if charge_costs else 0.0
        cash -= notional + cost
        total_costs += cost
        shares[sym] = shares.get(sym, 0) + qty
        entry_px[sym] = price
        trades.append({"date": date, "symbol": sym, "side": "buy", "qty": qty,
                       "price": price, "value": notional, "cost": cost, "reason": "rebalance"})
        return notional

    for date in dates:
        px = closes.loc[date]

        # --- intra-period exits, checked daily -----------------------------
        if shares and (disaster_stop_pct > 0 or trend_exit_fn is not None):
            trend_ok = trend_exit_fn(closes, date) if trend_exit_fn is not None else None
            for sym in list(shares):
                p = px.get(sym, np.nan)
                if not np.isfinite(p):
                    continue
                if disaster_stop_pct > 0 and sym in entry_px:
                    if p <= entry_px[sym] * (1.0 - disaster_stop_pct):
                        sell(sym, p, date, "disaster_stop")
                        continue
                if trend_ok is not None and not bool(trend_ok.get(sym, True)):
                    sell(sym, p, date, "trend_exit")

        # --- scheduled rebalance -------------------------------------------
        if date in rebals:
            target = signal_fn(closes, date, list(shares))
            target = [s for s in target if np.isfinite(px.get(s, np.nan))]

            pre_value = portfolio_value(px)
            traded = 0.0
            costs_before = total_costs

            # Sell what is no longer wanted, to free cash first.
            for sym in list(shares):
                if sym not in target:
                    traded += sell(sym, px.get(sym, np.nan), date, "rebalance")

            if target:
                value_now = portfolio_value(px)
                per_name = value_now / len(target)

                # Existing holdings are left to drift by default (weight_band=0).
                # Forcing every position back to equal weight each month would
                # generate large turnover for no expected return — and turnover
                # is the dominant cost lever here. Letting winners run is also
                # the behaviour momentum actually depends on. Set weight_band
                # (e.g. 0.5) to rebalance only positions that have drifted more
                # than that fraction away from target.
                if weight_band > 0:
                    for sym in list(shares):
                        if sym not in target:
                            continue
                        p = px.get(sym, np.nan)
                        if not np.isfinite(p):
                            continue
                        cur = shares[sym] * p
                        if cur > per_name * (1 + weight_band):
                            excess_qty = int((cur - per_name) // p)
                            if excess_qty >= 1:
                                proceeds = excess_qty * p
                                cost = (delivery_one_way_cost(proceeds, "sell", slippage_per_leg)
                                        if charge_costs else 0.0)
                                shares[sym] -= excess_qty
                                cash += proceeds - cost
                                total_costs += cost
                                traded += proceeds
                                trades.append({"date": date, "symbol": sym, "side": "sell",
                                               "qty": excess_qty, "price": p,
                                               "value": proceeds, "cost": cost,
                                               "reason": "trim"})

                # New entries share whatever cash is available, so a rebalance
                # never tries to spend money it doesn't have.
                new_entries = [s for s in target if shares.get(s, 0) == 0]
                for i, sym in enumerate(new_entries):
                    remaining = len(new_entries) - i
                    budget = min(per_name, cash / remaining if remaining else 0.0)
                    if budget > 0:
                        traded += buy(sym, px.get(sym, np.nan), budget, date)

                # Top up existing holdings only when explicitly rebalancing.
                if weight_band > 0:
                    for sym in target:
                        p = px.get(sym, np.nan)
                        if not np.isfinite(p) or shares.get(sym, 0) == 0:
                            continue
                        held_val = shares[sym] * p
                        if held_val < per_name * (1 - weight_band):
                            gap = min(per_name - held_val, cash)
                            if gap > 0:
                                traded += buy(sym, p, gap, date)

            # Cost must be recorded as a fraction of the book AT THE TIME it
            # was paid. Summing rupees over 15 years and dividing by the
            # STARTING capital overstates the drag by the growth multiple —
            # it reported 12.19%/yr on a book that grew 42.8x, when the true
            # drag was ~1%/yr. The equity curve was always right; only the
            # reported percentage was wrong.
            turnovers.append({"date": date,
                              "turnover": traded / pre_value if pre_value > 0 else 0.0,
                              "cost_frac": ((total_costs - costs_before) / pre_value
                                            if pre_value > 0 else 0.0),
                              "n_positions": len(shares)})
            if verbose:
                print(f"  {date.date()}  n={len(shares):3d}  "
                      f"turnover={traded/pre_value*100 if pre_value else 0:5.1f}%  "
                      f"value={portfolio_value(px):,.0f}")

        equity_curve.append({"date": date, "equity": portfolio_value(px),
                             "cash": cash, "n_positions": len(shares)})

    eq = pd.DataFrame(equity_curve).set_index("date")["equity"]
    tno = pd.DataFrame(turnovers).set_index("date") if turnovers else pd.DataFrame()

    return {
        "equity": eq,
        "turnover": tno,
        "trades": pd.DataFrame(trades),
        "total_costs": total_costs,
        "stats": summarise(eq, tno, total_costs, initial_capital),
    }


def summarise(equity: pd.Series, turnover: pd.DataFrame,
              total_costs: float, initial_capital: float) -> dict:
    """CAGR, volatility, Sharpe, max drawdown, turnover and cost drag."""
    if len(equity) < 2:
        return {}

    years = (equity.index[-1] - equity.index[0]).days / 365.25
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan

    rets = equity.pct_change().dropna()
    vol = rets.std() * np.sqrt(TRADING_DAYS)
    sharpe = (rets.mean() * TRADING_DAYS) / vol if vol > 0 else np.nan

    dd = equity / equity.cummax() - 1
    max_dd = dd.min()

    # Turnover must be ANNUALISED to be comparable across rebalance
    # frequencies — a 3% daily turnover and a 30% monthly turnover are wildly
    # different things, and comparing the raw per-rebalance averages would make
    # daily rebalancing look cheap when it is the opposite.
    if len(turnover):
        avg_tno = turnover["turnover"].mean()
        rebals_per_year = len(turnover) / years if years > 0 else np.nan
        annual_tno = avg_tno * rebals_per_year
    else:
        avg_tno = annual_tno = rebals_per_year = np.nan

    # Drag is the sum of each rebalance's cost as a fraction of the book at
    # that moment, annualised — NOT total rupees over initial capital, which
    # inflates by however much the portfolio compounded.
    if len(turnover) and "cost_frac" in turnover:
        cost_drag = turnover["cost_frac"].sum() / years if years > 0 else np.nan
    else:
        cost_drag = (total_costs / initial_capital) / years if years > 0 else np.nan
    # Average holding period implied by turnover, in months.
    avg_hold_months = 12.0 / annual_tno if annual_tno and annual_tno > 0 else np.nan

    return {
        "years": years,
        "total_return_pct": total_return * 100,
        "cagr_pct": cagr * 100,
        "vol_pct": vol * 100,
        "sharpe": sharpe,
        "max_dd_pct": max_dd * 100,
        "calmar": (cagr / abs(max_dd)) if max_dd < 0 else np.nan,
        "avg_turnover_pct": avg_tno * 100 if np.isfinite(avg_tno) else np.nan,
        "annual_turnover_pct": annual_tno * 100 if np.isfinite(annual_tno) else np.nan,
        "rebalances_per_year": rebals_per_year,
        "avg_hold_months": avg_hold_months,
        "total_costs": total_costs,
        "cost_drag_pct_yr": cost_drag * 100,
        "final_equity": equity.iloc[-1],
    }


def load_daily(data_dir: Path = None, repair_corporate_actions: bool = True,
               report: bool = False):
    """
    Load every daily CSV into aligned close and volume frames.

    Returns (closes, volumes) with a shared DatetimeIndex and one column per
    symbol.

    Gaps inside a symbol's own history are forward-filled — those are holidays
    and trading halts where the symbol simply did not trade, and leaving them
    NaN would misalign the 200-day and 252-day windows across symbols. Leading
    NaNs are deliberately NOT filled: the eligibility filter in momentum_xs
    reads NaN as 'not tradable yet', which is what keeps a name out of the
    universe before it listed.

    `repair_corporate_actions` truncates any symbol carrying an unadjusted
    split/demerger/relisting step so it starts after the event — see
    data/corporate_actions.py for why this is not optional for momentum. Pass
    False only to inspect the raw feed. Set `report=True` to return
    (closes, volumes, events) instead.
    """
    data_dir = data_dir or (PROJECT_ROOT / "data" / "daily")
    files = sorted(Path(data_dir).glob("*_1day.csv"))
    if not files:
        raise FileNotFoundError(
            f"No daily data in {data_dir}. Run:\n"
            f"  python data/fetch_universe.py --interval ONE_DAY --universe nifty200 --years 15\n"
            f"(must run off the corporate network — see RUN_AT_HOME.md)")

    closes, volumes = {}, {}
    for f in files:
        sym = f.stem.replace("_1day", "")
        d = pd.read_csv(f, parse_dates=["datetime"])
        d["date"] = pd.to_datetime(d["datetime"].dt.date)
        d = d.drop_duplicates(subset=["date"], keep="last").set_index("date")
        closes[sym] = d["close"]
        volumes[sym] = d["volume"]

    c = pd.DataFrame(closes).sort_index().ffill()
    v = pd.DataFrame(volumes).sort_index().reindex(c.index).fillna(0.0)

    events = {}
    if repair_corporate_actions:
        from data.corporate_actions import truncate_before_steps
        c, v, events = truncate_before_steps(c, v)

    return (c, v, events) if report else (c, v)

"""
Cost model for NSE cash-equity intraday trading (2026 tax year).

Implements the exact cost structure from phase-1-backtesting.md.
Position-size-aware: the flat ₹20 brokerage cap matters more on small trades.
"""


def brokerage_per_order(turnover: float) -> float:
    """Angel One: ₹20 flat OR 0.03% of turnover, whichever is lower."""
    return min(20.0, turnover * 0.0003)


def round_trip_cost(buy_value: float, sell_value: float) -> dict:
    """
    Calculate the full round-trip cost for one intraday trade.

    Parameters
    ----------
    buy_value : float
        Notional value of the buy leg (price × quantity).
    sell_value : float
        Notional value of the sell leg (price × quantity).

    Returns
    -------
    dict with individual components and total cost.
    """
    # Brokerage
    brok_buy = brokerage_per_order(buy_value)
    brok_sell = brokerage_per_order(sell_value)
    total_brokerage = brok_buy + brok_sell

    # STT — 0.025% on sell side only (intraday equity)
    stt = sell_value * 0.00025

    # Exchange transaction charges — ~0.003% both sides
    exchange_buy = buy_value * 0.00003
    exchange_sell = sell_value * 0.00003
    total_exchange = exchange_buy + exchange_sell

    # SEBI turnover fee — 0.0001% both sides
    sebi_buy = buy_value * 0.000001
    sebi_sell = sell_value * 0.000001
    total_sebi = sebi_buy + sebi_sell

    # Stamp duty — 0.003% on buy side only
    stamp = buy_value * 0.00003

    # GST — 18% on (brokerage + exchange charges + SEBI fee)
    gst = (total_brokerage + total_exchange + total_sebi) * 0.18

    # Slippage — 0.05% per leg (conservative estimate for liquid large-caps)
    slippage_buy = buy_value * 0.0005
    slippage_sell = sell_value * 0.0005
    total_slippage = slippage_buy + slippage_sell

    total = total_brokerage + stt + total_exchange + total_sebi + stamp + gst + total_slippage

    return {
        "brokerage": total_brokerage,
        "stt": stt,
        "exchange_charges": total_exchange,
        "sebi_fee": total_sebi,
        "stamp_duty": stamp,
        "gst": gst,
        "slippage": total_slippage,
        "total": total,
    }


def cost_as_fraction(trade_value: float) -> float:
    """
    Return the total round-trip cost as a fraction of trade value.

    Assumes buy_value ≈ sell_value ≈ trade_value (small P&L relative to
    notional, which is typical for intraday).
    """
    costs = round_trip_cost(trade_value, trade_value)
    return costs["total"] / trade_value


def per_side_commission(trade_value: float) -> float:
    """
    Return the single-leg (per-order) commission fraction for Backtesting.py.

    Backtesting.py applies the `commission` parameter to BOTH entry and exit
    orders. Therefore, commission passed to Backtest must be the single-leg
    cost (half the round-trip) so the total round-trip cost matches the model.

    Example:
    >>> commission = per_side_commission(50_000)  # ~0.00103 (0.103% per leg -> 0.206% round trip)
    """
    return cost_as_fraction(trade_value) / 2.0



def angel_intraday_commission(order_size: int, price: float) -> float:
    """
    Exact per-order statutory cost for NSE cash-equity intraday, in rupees.

    Designed to be passed directly as Backtesting.py's `commission` argument,
    which accepts a callable `func(order_size, price) -> cash`. `order_size` is
    negative for sell/short orders, which is what lets us apply the sell-only
    STT and buy-only stamp duty correctly instead of averaging them.

    This is strictly better than passing `per_side_commission(...)` as a flat
    fraction, because:
      - the flat-Rs.20 brokerage cap is applied against the *actual* turnover
        of each order rather than one assumed position size,
      - STT is charged on the sell leg only, not half-charged on both legs,
      - stamp duty is charged on the buy leg only.

    NOTE: slippage is deliberately NOT included here. Slippage moves the fill
    price, it is not a fee, so it belongs in Backtesting.py's `spread`
    parameter (which fills buys at price*(1+spread) and sells at
    price*(1-spread)). Use SLIPPAGE_PER_LEG below for that.
    """
    turnover = abs(order_size) * price
    is_sell = order_size < 0

    brokerage = brokerage_per_order(turnover)
    stt = turnover * 0.00025 if is_sell else 0.0
    exchange = turnover * 0.00003
    sebi = turnover * 0.000001
    stamp = 0.0 if is_sell else turnover * 0.00003
    gst = (brokerage + exchange + sebi) * 0.18

    return brokerage + stt + exchange + sebi + stamp + gst


# Per-leg slippage, passed to Backtesting.py as `spread`.
# 0.0005 = 5 bps per leg = 10 bps round trip (the conservative large-cap
# estimate from phase-1-backtesting.md section 7). Keep this as the headline
# assumption for go/no-go decisions; report a 2 bps variant alongside it.
SLIPPAGE_PER_LEG = 0.0005


if __name__ == "__main__":
    # Quick sanity check: print costs at different position sizes
    print(f"{'Position Size':>15} | {'Total Cost':>12} | {'Cost %':>8}")
    print("-" * 45)
    for size in [10_000, 25_000, 50_000, 100_000, 200_000, 500_000]:
        costs = round_trip_cost(size, size)
        pct = (costs["total"] / size) * 100
        print(f"Rs.{size:>12,} | Rs.{costs['total']:>9,.2f} | {pct:>7.3f}%")

    print("\n--- Breakdown for Rs.50,000 trade ---")
    detail = round_trip_cost(50_000, 50_000)
    for k, v in detail.items():
        print(f"  {k:20s}: Rs.{v:,.2f}")

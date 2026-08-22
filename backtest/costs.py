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


# ---------------------------------------------------------------------------
# Delivery (CNC) cost model — for multi-day/positional holding
# ---------------------------------------------------------------------------
#
# Everything above this line is the INTRADAY (MIS) model and is kept for the
# historical record of the intraday work (which was tested and rejected — see
# Learning-T/phase-1-backtesting.md). Delivery is a materially different and
# more expensive structure, and conflating the two is an easy way to build a
# strategy that looks profitable and isn't.
#
# The dominant difference is STT: 0.1% on BOTH legs for delivery, versus
# 0.025% sell-only for intraday. That alone is 20 bps of round-trip cost and,
# being purely proportional, it never amortises with position size. Delivery
# also adds DP (depository) charges on the sell leg, which are a flat rupee
# amount per scrip and therefore hurt small positions badly.
#
# Rates verified Aug 2026. Brokerage is Angel One's post-Nov-2024 delivery
# schedule (they no longer offer free delivery).

DELIVERY_BROKERAGE_MIN = 5.0        # Rs. floor per order
DELIVERY_BROKERAGE_CAP = 20.0       # Rs. ceiling per order
DELIVERY_BROKERAGE_RATE = 0.001     # 0.1% of turnover
DELIVERY_STT = 0.001                # 0.1% — BOTH legs (vs 0.025% sell-only intraday)
DELIVERY_STAMP = 0.00015            # 0.015% — buy only (vs 0.003% intraday)
EXCHANGE_TXN = 0.0000297            # 0.00297% NSE, both legs
SEBI_FEE = 0.000001                 # 0.0001%, both legs
GST_RATE = 0.18
DP_CHARGE_PER_SELL = 20.0           # Rs. per scrip on the sell leg (CDSL/Angel One)


def delivery_brokerage_per_order(turnover: float) -> float:
    """Angel One delivery: Rs.20 or 0.1% of turnover, whichever is lower, min Rs.5."""
    return max(DELIVERY_BROKERAGE_MIN,
               min(DELIVERY_BROKERAGE_CAP, turnover * DELIVERY_BROKERAGE_RATE))


def delivery_round_trip(buy_value: float, sell_value: float,
                        slippage_per_leg: float = SLIPPAGE_PER_LEG) -> dict:
    """
    Full round-trip cost in rupees for one delivery (CNC) position.

    Unlike the intraday model, slippage is included here rather than being
    handed to a `spread` parameter — the portfolio backtester charges a single
    cash cost per rebalance rather than adjusting individual fill prices.

    Returns a dict of components plus 'total'.
    """
    brok_buy = delivery_brokerage_per_order(buy_value)
    brok_sell = delivery_brokerage_per_order(sell_value)
    total_brokerage = brok_buy + brok_sell

    stt = (buy_value + sell_value) * DELIVERY_STT          # BOTH legs
    exchange = (buy_value + sell_value) * EXCHANGE_TXN
    sebi = (buy_value + sell_value) * SEBI_FEE
    stamp = buy_value * DELIVERY_STAMP                     # buy only
    dp = DP_CHARGE_PER_SELL                                # sell only, per scrip
    gst = (total_brokerage + exchange + sebi + dp) * GST_RATE
    slippage = (buy_value + sell_value) * slippage_per_leg

    total = total_brokerage + stt + exchange + sebi + stamp + dp + gst + slippage

    return {
        "brokerage": total_brokerage,
        "stt": stt,
        "exchange_charges": exchange,
        "sebi_fee": sebi,
        "stamp_duty": stamp,
        "dp_charges": dp,
        "gst": gst,
        "slippage": slippage,
        "total": total,
    }


def delivery_cost_bps(position_value: float,
                      slippage_per_leg: float = SLIPPAGE_PER_LEG) -> float:
    """Round-trip delivery cost in basis points of position value."""
    if position_value <= 0:
        return 0.0
    c = delivery_round_trip(position_value, position_value, slippage_per_leg)
    return c["total"] / position_value * 1e4


def delivery_one_way_cost(traded_value: float, side: str,
                          slippage_per_leg: float = SLIPPAGE_PER_LEG) -> float:
    """
    Cost in rupees for a single delivery leg.

    The portfolio backtester needs this because a rebalance buys some names and
    sells others independently — charging a symmetric half of a round trip would
    misplace STT (both legs, so symmetric), stamp duty (buy only) and DP
    charges (sell only).

    `side` is 'buy' or 'sell'.
    """
    if traded_value <= 0:
        return 0.0
    is_buy = side.lower() == "buy"

    brokerage = delivery_brokerage_per_order(traded_value)
    stt = traded_value * DELIVERY_STT
    exchange = traded_value * EXCHANGE_TXN
    sebi = traded_value * SEBI_FEE
    stamp = traded_value * DELIVERY_STAMP if is_buy else 0.0
    dp = 0.0 if is_buy else DP_CHARGE_PER_SELL
    gst = (brokerage + exchange + sebi + dp) * GST_RATE
    slippage = traded_value * slippage_per_leg

    return brokerage + stt + exchange + sebi + stamp + dp + gst + slippage


if __name__ == "__main__":
    SIZES = [10_000, 25_000, 50_000, 100_000, 200_000, 500_000]

    print("=" * 68)
    print("  INTRADAY (MIS) — round-trip cost")
    print("=" * 68)
    print(f"{'Position Size':>15} | {'Total Cost':>12} | {'Cost %':>8} | {'bps':>7}")
    print("-" * 55)
    for size in SIZES:
        costs = round_trip_cost(size, size)
        pct = (costs["total"] / size) * 100
        print(f"Rs.{size:>12,} | Rs.{costs['total']:>9,.2f} | {pct:>7.3f}% | {pct*100:>6.1f}")

    print("\n--- Breakdown for Rs.50,000 intraday trade ---")
    for k, v in round_trip_cost(50_000, 50_000).items():
        print(f"  {k:20s}: Rs.{v:,.2f}")

    print("\n" + "=" * 68)
    print("  DELIVERY (CNC) — round-trip cost")
    print("=" * 68)
    print(f"{'Position Size':>15} | {'Total Cost':>12} | {'Cost %':>8} | {'bps':>7}")
    print("-" * 55)
    for size in SIZES:
        costs = delivery_round_trip(size, size)
        pct = (costs["total"] / size) * 100
        print(f"Rs.{size:>12,} | Rs.{costs['total']:>9,.2f} | {pct:>7.3f}% | {pct*100:>6.1f}")

    print("\n--- Breakdown for Rs.100,000 delivery position ---")
    detail = delivery_round_trip(100_000, 100_000)
    for k, v in detail.items():
        share = v / detail["total"] * 100
        print(f"  {k:20s}: Rs.{v:>9,.2f}  ({share:>5.1f}%)")

    print("\n--- Why delivery is structurally more expensive ---")
    for size in [50_000, 100_000, 200_000, 500_000]:
        i = cost_as_fraction(size) * 1e4
        d = delivery_cost_bps(size)
        print(f"  Rs.{size:>8,}: intraday {i:>5.1f} bps | delivery {d:>5.1f} bps "
              f"| {d/i:>4.1f}x")
    print("\n  STT alone is 20.0 bps of the delivery cost and is purely")
    print("  proportional, so it never amortises with position size.")

    print("\n--- Sensitivity to the slippage assumption (delivery) ---")
    print(f"{'position':>10} | " + " | ".join(f"{s} bps/leg" for s in [5, 3, 2, 1]))
    print("-" * 52)
    for size in [50_000, 100_000, 200_000, 500_000]:
        row = " | ".join(f"{delivery_cost_bps(size, s/1e4):9.1f}" for s in [5, 3, 2, 1])
        print(f"Rs.{size:>7,} | {row}")

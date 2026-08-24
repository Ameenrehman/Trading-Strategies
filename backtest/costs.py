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



# ---------------------------------------------------------------------------
# Angel One 2026 schedule, calibrated against a real contract note
# ---------------------------------------------------------------------------
#
# Everything above this line is the ORIGINAL cost model and is deliberately
# left alone: the intraday rejection in Part 1 of the README and the delivery
# results in Part 2 were both measured with it, and silently moving those
# numbers would make the published record unreproducible.
#
# It is, however, wrong about intraday brokerage. The model above charges
# min(Rs.20, 0.03% x turnover). Angel One's actual intraday rate is the same
# max(Rs.5, min(Rs.20, 0.1%)) schedule it uses for delivery — they no longer
# price MIS more cheaply than CNC. A real round trip supplied by the account
# holder:
#
#     buy  Rs.4,852 -> Rs.6.08        sell Rs.4,640 -> Rs.7.07
#     total Rs.13.15 = 27.1 bps of turnover, before slippage
#
# The legacy model prices that same trade at Rs.5.01 (10.3 bps). It understates
# real intraday cost by 2.8x. This does not overturn Part 1 — it makes its
# rejection wider, since the measured +11.26 bps gross edge was already below
# the ~14 bps the old model charged, and the real toll is roughly 37 bps once
# slippage is added.
#
# Two details are needed to reproduce a contract note to the paisa, and both
# only matter at small size:
#   - STT and stamp duty are rounded to the nearest rupee, not carried in
#     paise. On a Rs.4,640 sell, STT of Rs.1.16 is billed as Rs.1.
#   - The Rs.5 brokerage floor binds below Rs.5,000 of turnover, which is
#     exactly the regime the hybrid strategy trades in.

ANGEL_BROKERAGE_MIN = 5.0
ANGEL_BROKERAGE_CAP = 20.0
ANGEL_BROKERAGE_RATE = 0.001        # 0.1%, intraday AND delivery as of 2026
INTRADAY_STT_SELL = 0.00025         # 0.025%, sell leg only
INTRADAY_STAMP_BUY = 0.00003        # 0.003%, buy leg only


def angel_brokerage_per_order(turnover: float) -> float:
    """Angel One 2026: Rs.20 or 0.1% of turnover, whichever is lower, floor Rs.5."""
    return max(ANGEL_BROKERAGE_MIN,
               min(ANGEL_BROKERAGE_CAP, turnover * ANGEL_BROKERAGE_RATE))


def _statutory(x: float, round_to_rupee: bool = True) -> float:
    """STT and stamp duty are billed in whole rupees."""
    return round(x) if round_to_rupee else x


def intraday_leg_2026(turnover: float, side: str,
                      round_to_rupee: bool = True) -> dict:
    """
    Cost of one intraday (MIS) leg under the corrected schedule.

    `side` is 'buy' or 'sell'. Reproduces a real Angel One contract note:
    intraday_leg_2026(4852, 'buy')['total'] == 6.08
    intraday_leg_2026(4640, 'sell')['total'] == 7.07
    """
    is_sell = side.lower() == "sell"
    brokerage = angel_brokerage_per_order(turnover)
    exchange = turnover * EXCHANGE_TXN
    sebi = turnover * SEBI_FEE
    stt = _statutory(turnover * INTRADAY_STT_SELL, round_to_rupee) if is_sell else 0.0
    stamp = 0.0 if is_sell else _statutory(turnover * INTRADAY_STAMP_BUY, round_to_rupee)
    gst = (brokerage + exchange + sebi) * GST_RATE

    return {
        "brokerage": brokerage, "stt": stt, "exchange_charges": exchange,
        "sebi_fee": sebi, "stamp_duty": stamp, "gst": gst,
        "total": brokerage + stt + exchange + sebi + stamp + gst,
    }


def intraday_round_trip_2026(buy_value: float, sell_value: float,
                             slippage_per_leg: float = SLIPPAGE_PER_LEG,
                             round_to_rupee: bool = True) -> dict:
    """Corrected intraday round trip. Same dict shape as round_trip_cost()."""
    b = intraday_leg_2026(buy_value, "buy", round_to_rupee)
    s = intraday_leg_2026(sell_value, "sell", round_to_rupee)
    slippage = (buy_value + sell_value) * slippage_per_leg
    out = {k: b[k] + s[k] for k in b}
    out["slippage"] = slippage
    out["total"] += slippage
    return out


def intraday_cost_bps_2026(position_value: float,
                           slippage_per_leg: float = SLIPPAGE_PER_LEG) -> float:
    """Corrected intraday round-trip cost in bps of position value."""
    if position_value <= 0:
        return 0.0
    c = intraday_round_trip_2026(position_value, position_value, slippage_per_leg)
    return c["total"] / position_value * 1e4


# ---------------------------------------------------------------------------
# Hybrid (MIS buy -> CNC sell) cost model — for any intraday-entry position
# that is converted to delivery rather than squared off
# ---------------------------------------------------------------------------
#
# A position entered as MIS and converted to CNC before the cutoff is priced by
# neither model above. It pays intraday-rate brokerage on the buy (brokerage is
# billed at order placement, and the order was an MIS order), then the full
# delivery structure on the sell: 0.1% STT, Rs.20 DP per scrip, delivery-rate
# brokerage. Under the 2026 schedule the two brokerage rates are identical
# anyway, so the difference is entirely STT, stamp duty and DP.
#
# The one genuinely uncertain input is what conversion does to the BUY leg's
# STT. STT is a statutory levy on the settlement, not on the order, so a
# position that ends the day in the demat account is arguably a delivery buy
# and attracts 0.1% rather than 0.025%-sell-only treatment. Brokers differ in
# how they present this and the contract note is the only authority.
# `converted_buy_is_delivery` exposes the choice; it defaults to True because
# assuming the cheaper treatment is how a backtest talks itself into a strategy
# that isn't there. The difference is ~10 bps on a Rs.5,000 position.
#
# WHY THIS MATTERS MORE THAN THE PERCENTAGES: DP is a flat Rs.20 + GST = Rs.23.60
# per scrip per sell, confirmed against the account holder's own charges. On
# Rs.5,000 that single line is 47 bps. On Rs.1,667 — which is what splitting
# Rs.5,000 across three names produces — it is 142 bps, and it swamps every
# other component combined. Small capital and multiple concurrent positions are
# not independent choices here.

def hybrid_round_trip(buy_value: float, sell_value: float,
                      converted_buy_is_delivery: bool = True,
                      slippage_per_leg: float = SLIPPAGE_PER_LEG,
                      round_to_rupee: bool = True) -> dict:
    """
    Full round-trip cost in rupees for one MIS-entry -> CNC-exit position.

    Buy leg  : intraday brokerage; STT and stamp depend on whether conversion
               reclassifies the buy as a delivery trade (see module comment).
    Sell leg : delivery brokerage, 0.1% STT, Rs.20 DP charge.

    Returns a dict of components plus 'total', matching the shape of
    round_trip_cost() and delivery_round_trip() so callers can swap them.
    """
    brok_buy = angel_brokerage_per_order(buy_value)
    brok_sell = angel_brokerage_per_order(sell_value)
    total_brokerage = brok_buy + brok_sell

    if converted_buy_is_delivery:
        stt_buy = _statutory(buy_value * DELIVERY_STT, round_to_rupee)
        stamp = _statutory(buy_value * DELIVERY_STAMP, round_to_rupee)
    else:
        stt_buy = 0.0
        stamp = _statutory(buy_value * INTRADAY_STAMP_BUY, round_to_rupee)
    stt_sell = _statutory(sell_value * DELIVERY_STT, round_to_rupee)
    stt = stt_buy + stt_sell

    exchange = (buy_value + sell_value) * EXCHANGE_TXN
    sebi = (buy_value + sell_value) * SEBI_FEE
    dp = DP_CHARGE_PER_SELL
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


def hybrid_cost_bps(position_value: float,
                    converted_buy_is_delivery: bool = True,
                    slippage_per_leg: float = SLIPPAGE_PER_LEG) -> float:
    """Round-trip hybrid cost in basis points of position value."""
    if position_value <= 0:
        return 0.0
    c = hybrid_round_trip(position_value, position_value,
                          converted_buy_is_delivery, slippage_per_leg)
    return c["total"] / position_value * 1e4


def intraday_cost_bps(position_value: float) -> float:
    """Round-trip intraday (MIS) cost in bps — the bps-facing twin of cost_as_fraction."""
    if position_value <= 0:
        return 0.0
    return cost_as_fraction(position_value) * 1e4


def net_levels(entry: float, shares: int, tp_pct: float, sl_pct: float,
               cost_fn=hybrid_round_trip, **cost_kwargs) -> dict:
    """
    Turn gross take-profit and stop-loss percentages into what actually lands.

    A '+5% target and -3% stop' is a statement about prices, not about money.
    On Rs.5,000 the round trip is ~95 bps, so the real pair is +4.05% / -3.95%
    and the reward:risk collapses from the advertised 1.67 to 1.03 — which
    moves the breakeven win rate from 37.5% to 49.3%. Reports should quote
    these numbers and never the gross ones.

    `sl_pct` is given as a positive magnitude (0.03 means a 3% stop).

    Returns net percentages, the realised reward:risk, and the win rate needed
    to break even at that R:R.
    """
    buy_value = entry * shares
    if buy_value <= 0:
        return {}

    tp_value = entry * (1.0 + tp_pct) * shares
    sl_value = entry * (1.0 - sl_pct) * shares

    cost_tp = cost_fn(buy_value, tp_value, **cost_kwargs)["total"]
    cost_sl = cost_fn(buy_value, sl_value, **cost_kwargs)["total"]

    net_tp = (tp_value - buy_value - cost_tp) / buy_value
    net_sl = (sl_value - buy_value - cost_sl) / buy_value

    rr = (net_tp / -net_sl) if net_sl < 0 else float("inf")
    breakeven = (-net_sl / (net_tp - net_sl)) if net_tp > net_sl else float("nan")

    return {
        "position_value": buy_value,
        "gross_tp_pct": tp_pct,
        "gross_sl_pct": -sl_pct,
        "net_tp_pct": net_tp,
        "net_sl_pct": net_sl,
        "cost_bps": (cost_tp + cost_sl) / 2.0 / buy_value * 1e4,
        "rr": rr,
        "breakeven_win_rate": breakeven,
    }
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

    print("\n" + "=" * 68)
    print("  HYBRID (MIS buy -> CNC sell) — the small-capital regime")
    print("=" * 68)
    print("  The tables above start at Rs.10,000 and hide what happens below it.")
    print("  Rs.5,000 split across 1-3 names is the regime that actually matters")
    print("  at this account size, and the flat DP charge dominates it.\n")
    SMALL = [1_667, 2_500, 5_000, 10_000, 25_000, 50_000]
    print(f"{'position':>10} | {'MIS old':>8} | {'MIS real':>9} | {'HYB opt':>8} "
          f"| {'HYB cons':>9} | {'CNC':>7} | {'DP+GST':>7}")
    print("-" * 78)
    for v in SMALL:
        dp_only = (DP_CHARGE_PER_SELL * (1 + GST_RATE)) / v * 1e4
        print(f"Rs.{v:>7,} | {intraday_cost_bps(v):>8.1f} | {intraday_cost_bps_2026(v):>9.1f} "
              f"| {hybrid_cost_bps(v, False):>8.1f} | {hybrid_cost_bps(v, True):>9.1f} "
              f"| {delivery_cost_bps(v):>7.1f} | {dp_only:>7.1f}")
    print("\n  All figures in bps of position value. 'opt'/'cons' is whether")
    print("  MIS->CNC conversion reclassifies the BUY leg's STT to delivery.")
    print("  'MIS old' is the legacy 0.03% brokerage model, kept so Part 1 of")
    print("  the README still reproduces; 'MIS real' is Angel One's actual")
    print("  2026 schedule, calibrated below.")

    print("\n--- Known-answer test: a real Angel One intraday round trip ---")
    checks = [(4_852, "buy", 6.08), (4_640, "sell", 7.07)]
    for turnover, side, expected in checks:
        got = intraday_leg_2026(turnover, side)["total"]
        ok = "PASS" if abs(got - expected) < 0.01 else "FAIL"
        print(f"  {side:<4} Rs.{turnover:>6,} -> Rs.{got:>5.2f}  "
              f"(contract note Rs.{expected:.2f})  {ok}")
    rt = sum(intraday_leg_2026(t, sd)["total"] for t, sd, _ in checks)
    legacy = round_trip_cost(4_852, 4_640)["total"] - (4_852 + 4_640) * SLIPPAGE_PER_LEG
    print(f"       round trip  Rs.{rt:>5.2f}  (contract note Rs.13.15)")
    print(f"  Legacy model prices the same trade at Rs.{legacy:.2f} "
          f"— understated {rt / legacy:.1f}x.")

    print("\n--- Breakdown for a Rs.5,000 hybrid position (conservative) ---")
    detail = hybrid_round_trip(5_000, 5_000)
    for k, v in detail.items():
        share = v / detail["total"] * 100
        print(f"  {k:20s}: Rs.{v:>8,.2f}  ({share:>5.1f}%)")

    print("\n--- What Rs.5,000 of capital buys you, by concurrent positions ---")
    print(f"{'positions':>10} | {'each':>9} | {'cost':>8} | {'net TP':>8} "
          f"| {'net SL':>8} | {'R:R':>5} | {'breakeven':>9}")
    print("-" * 72)
    breakevens = {}
    for n in (1, 2, 3):
        alloc = 5_000 / n
        shares = max(int(alloc // 500), 1)          # a Rs.500 share, for illustration
        lv = net_levels(500.0, shares, 0.05, 0.03)
        breakevens[n] = lv["breakeven_win_rate"] * 100
        print(f"{n:>10} | Rs.{alloc:>6,.0f} | {lv['cost_bps']:>7.1f}b "
              f"| {lv['net_tp_pct']*100:>+7.2f}% | {lv['net_sl_pct']*100:>+7.2f}% "
              f"| {lv['rr']:>5.2f} | {lv['breakeven_win_rate']*100:>8.1f}%")
    print("\n  The advertised '+5%/-3%, needs 37.5% win rate' is a gross-price")
    print(f"  statement. One position needs {breakevens[1]:.0f}%; splitting Rs.5,000")
    print(f"  three ways needs {breakevens[3]:.0f}%, because the flat Rs.20 DP charge is")
    print("  paid per scrip regardless of how small the position is.")

    print("\n--- Slippage barely moves the hybrid at this size ---")
    for s in (5, 3, 2, 1, 0):
        print(f"  {s} bps/leg -> Rs.5,000 hybrid = "
              f"{hybrid_cost_bps(5_000, True, s / 1e4):5.1f} bps round trip")
    print("\n  5 -> 0 bps/leg moves the total by 10 bps out of ~95. The cost here")
    print("  is almost entirely statutory and exactly known, so 'but slippage is")
    print("  only assumed' is not an available objection to this result.")

"""
Overfitting validation suite for backtested strategies.

Implements the checklist from phase-1-backtesting.md:
1. Multi-regime check
2. Minimum trade count
3. Parameter robustness (nearby values should perform similarly)
4. Walk-forward validation
5. Random entry benchmark
6. Out-of-sample holdout (last 6 months, test once)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from backtesting import Backtest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from strategies.orb_strategy import ORBStrategy
from backtest.costs import cost_as_fraction
from backtest.run_backtest import load_data


# The 5-minute set lives in its own folder so the daily (delivery) data
# under data/daily/ stays cleanly separated from the intraday work.
DATA_DIR = PROJECT_ROOT / "data" / "intraday_5min"
RESULTS_DIR = Path(__file__).parent / "results"
COMMISSION = cost_as_fraction(50_000)

# Minimum trades threshold
MIN_TRADES = 100


def check_1_multi_regime(data: pd.DataFrame, symbol: str) -> bool:
    """Check that data spans multiple market regimes."""
    print(f"\n[1] Multi-Regime Check: {symbol}")
    print("-" * 40)

    # Calculate monthly returns to identify regimes
    daily = data.resample("D")["Close"].last().dropna()
    monthly = daily.resample("ME").last().pct_change().dropna()

    total_months = len(monthly)
    up_months = (monthly > 0.02).sum()
    down_months = (monthly < -0.02).sum()
    flat_months = total_months - up_months - down_months

    # Check for crash (any month with > 5% drop)
    crash_months = (monthly < -0.05).sum()

    print(f"  Total months: {total_months}")
    print(f"  Trending up (>+2%): {up_months}")
    print(f"  Trending down (<-2%): {down_months}")
    print(f"  Flat/sideways: {flat_months}")
    print(f"  Crash months (<-5%): {crash_months}")

    # Need at least some of each
    has_variety = up_months >= 3 and down_months >= 2 and flat_months >= 2
    if has_variety:
        print("  [PASS] Data spans multiple market regimes.")
    else:
        print("  [WARN] Data may not cover enough regime variety.")

    return has_variety


def check_2_trade_count(stats, symbol: str) -> bool:
    """Check minimum trade count."""
    print(f"\n[2] Minimum Trade Count: {symbol}")
    print("-" * 40)

    n_trades = stats.get("# Trades", 0)
    print(f"  Total trades: {n_trades}")
    print(f"  Threshold: {MIN_TRADES}")

    if n_trades >= MIN_TRADES:
        print(f"  [PASS] Sufficient trades ({n_trades} >= {MIN_TRADES}).")
        return True
    elif n_trades >= 30:
        print(f"  [WARN] Bare minimum met ({n_trades} >= 30), but < {MIN_TRADES}.")
        return False
    else:
        print(f"  [FAIL] Too few trades ({n_trades}). Results are not statistically meaningful.")
        return False


def check_3_parameter_robustness(data: pd.DataFrame, symbol: str) -> bool:
    """
    Check that nearby parameter values produce similar results.
    A sharp cliff at the 'best' value is an overfitting red flag.
    """
    print(f"\n[3] Parameter Robustness: {symbol}")
    print("-" * 40)

    # Test or_bars: 4, 5, 6, 7, 8 (default is 6)
    # Test rr_ratio: 1.5, 1.75, 2.0, 2.25, 2.5
    or_bars_range = [4, 5, 6, 7, 8]
    rr_range = [1.5, 1.75, 2.0, 2.25, 2.5]

    results = []

    # Vary or_bars with fixed rr_ratio=2.0
    print("  Varying or_bars (rr_ratio=2.0):")
    for ob in or_bars_range:
        try:
            bt = Backtest(data, ORBStrategy, cash=100_000, commission=COMMISSION,
                          exclusive_orders=True, trade_on_close=True)
            stats = bt.run(or_bars=ob, rr_ratio=2.0, min_range_pct=0.0)
            ret = stats.get("Return [%]", 0)
            sharpe = stats.get("Sharpe Ratio", 0)
            trades = stats.get("# Trades", 0)
            results.append({"param": f"or_bars={ob}", "return": ret, "sharpe": sharpe, "trades": trades})
            print(f"    or_bars={ob}: Return={ret:+.2f}%, Sharpe={sharpe:.3f}, Trades={trades}")
        except Exception as e:
            print(f"    or_bars={ob}: ERROR - {e}")

    # Vary rr_ratio with fixed or_bars=6
    print("  Varying rr_ratio (or_bars=6):")
    for rr in rr_range:
        try:
            bt = Backtest(data, ORBStrategy, cash=100_000, commission=COMMISSION,
                          exclusive_orders=True, trade_on_close=True)
            stats = bt.run(or_bars=6, rr_ratio=rr, min_range_pct=0.0)
            ret = stats.get("Return [%]", 0)
            sharpe = stats.get("Sharpe Ratio", 0)
            trades = stats.get("# Trades", 0)
            results.append({"param": f"rr_ratio={rr}", "return": ret, "sharpe": sharpe, "trades": trades})
            print(f"    rr_ratio={rr}: Return={ret:+.2f}%, Sharpe={sharpe:.3f}, Trades={trades}")
        except Exception as e:
            print(f"    rr_ratio={rr}: ERROR - {e}")

    # Check for cliff effects: if the best result is >2x the median, flag it
    if results:
        returns = [r["return"] for r in results]
        median_ret = np.median(returns)
        max_ret = max(returns)
        min_ret = min(returns)
        spread = max_ret - min_ret

        print(f"\n  Return range: {min_ret:+.2f}% to {max_ret:+.2f}% (spread: {spread:.2f}%)")
        print(f"  Median return: {median_ret:+.2f}%")

        # If spread is huge relative to median, it's a red flag
        if median_ret != 0 and abs(spread / abs(median_ret)) > 3:
            print("  [WARN] Large spread relative to median - potential overfitting!")
            return False
        else:
            print("  [PASS] Parameter sensitivity looks reasonable.")
            return True

    return False


def check_4_walk_forward(data: pd.DataFrame, symbol: str, n_splits: int = 4) -> bool:
    """
    Walk-forward validation: train on rolling window, test on next unseen segment.
    """
    print(f"\n[4] Walk-Forward Validation: {symbol}")
    print("-" * 40)

    total_bars = len(data)
    split_size = total_bars // (n_splits + 1)  # +1 for the training window

    if split_size < 500:
        print(f"  [SKIP] Not enough data for {n_splits}-fold walk-forward (need more bars).")
        return False

    fold_results = []

    for fold in range(n_splits):
        train_start = fold * split_size
        train_end = (fold + 1) * split_size
        test_start = train_end
        test_end = min(test_start + split_size, total_bars)

        if test_end <= test_start:
            break

        train_data = data.iloc[train_start:train_end]
        test_data = data.iloc[test_start:test_end]

        # Train: find best or_bars on training data
        best_ret = -np.inf
        best_ob = 6

        for ob in [4, 5, 6, 7, 8]:
            try:
                bt = Backtest(train_data, ORBStrategy, cash=100_000, commission=COMMISSION,
                              exclusive_orders=True, trade_on_close=True)
                stats = bt.run(or_bars=ob, rr_ratio=2.0, min_range_pct=0.0)
                ret = stats.get("Return [%]", 0)
                if ret > best_ret:
                    best_ret = ret
                    best_ob = ob
            except Exception:
                pass

        # Test: use best_ob on out-of-sample test data
        try:
            bt = Backtest(test_data, ORBStrategy, cash=100_000, commission=COMMISSION,
                          exclusive_orders=True, trade_on_close=True)
            test_stats = bt.run(or_bars=best_ob, rr_ratio=2.0, min_range_pct=0.0)
            test_ret = test_stats.get("Return [%]", 0)
            test_trades = test_stats.get("# Trades", 0)
            fold_results.append(test_ret)
            print(f"  Fold {fold+1}: train or_bars={best_ob} (ret={best_ret:+.2f}%), "
                  f"test ret={test_ret:+.2f}%, trades={test_trades}")
        except Exception as e:
            print(f"  Fold {fold+1}: ERROR - {e}")

    if fold_results:
        avg_oos = np.mean(fold_results)
        positive_folds = sum(1 for r in fold_results if r > 0)
        print(f"\n  Average out-of-sample return: {avg_oos:+.2f}%")
        print(f"  Positive folds: {positive_folds}/{len(fold_results)}")

        if avg_oos > 0 and positive_folds >= len(fold_results) // 2:
            print("  [PASS] Walk-forward shows consistent out-of-sample performance.")
            return True
        else:
            print("  [WARN] Walk-forward results are weak or inconsistent.")
            return False

    return False


def check_5_random_entry_benchmark(data: pd.DataFrame, symbol: str, n_trials: int = 50) -> bool:
    """
    Compare strategy against random entries with same exits.
    If the strategy can't beat random entries, the entry logic isn't adding value.
    """
    print(f"\n[5] Random Entry Benchmark: {symbol}")
    print("-" * 40)

    # Run the actual strategy
    bt = Backtest(data, ORBStrategy, cash=100_000, commission=COMMISSION,
                  exclusive_orders=True, trade_on_close=True)
    real_stats = bt.run(or_bars=6, rr_ratio=2.0, min_range_pct=0.0)
    real_return = real_stats.get("Return [%]", 0)
    print(f"  Strategy return: {real_return:+.2f}%")

    # Run random entry trials
    # For random entries, we use a strategy that enters at random times
    # with the same SL/TP structure
    class RandomEntryStrategy(ORBStrategy):
        """Same as ORB but enters at random times instead of on breakout."""
        _rng = None

        def next(self):
            bar_time = self.data.index[-1]
            if hasattr(bar_time, 'date'):
                bar_date = bar_time.date()
            else:
                bar_date = bar_time

            bar_hour = bar_time.hour if hasattr(bar_time, 'hour') else 0
            bar_minute = bar_time.minute if hasattr(bar_time, 'minute') else 0
            bar_time_mins = bar_hour * 60 + bar_minute

            # New day reset
            if bar_date != self._current_date:
                self._current_date = bar_date
                self._bar_count_today = 0
                self._range_high = -np.inf
                self._range_low = np.inf
                self._traded_today = False

            self._bar_count_today += 1

            # Still build opening range (for SL/TP sizing)
            if self._bar_count_today <= self.or_bars:
                self._range_high = max(self._range_high, self.data.High[-1])
                self._range_low = min(self._range_low, self.data.Low[-1])
                return

            # EOD exit
            if bar_time_mins >= 915:
                if self.position:
                    self.position.close()
                return

            if self._traded_today:
                return

            range_size = self._range_high - self._range_low
            if range_size <= 0 or np.isinf(range_size):
                return

            # Random entry instead of breakout
            if self._rng is None:
                self._rng = np.random.RandomState(42)

            if self._rng.random() < 0.1:  # ~10% chance per bar
                self._traded_today = True
                risk = range_size
                tp_distance = risk * self.rr_ratio
                if self._rng.random() < 0.5:
                    self.buy(sl=self._range_low, tp=self.data.Close[-1] + tp_distance)
                else:
                    self.sell(sl=self._range_high, tp=self.data.Close[-1] - tp_distance)

    random_returns = []
    for trial in range(n_trials):
        try:
            RandomEntryStrategy._rng = np.random.RandomState(trial)
            bt = Backtest(data, RandomEntryStrategy, cash=100_000, commission=COMMISSION,
                          exclusive_orders=True, trade_on_close=True)
            stats = bt.run(or_bars=6, rr_ratio=2.0, min_range_pct=0.0)
            random_returns.append(stats.get("Return [%]", 0))
        except Exception:
            pass

    if random_returns:
        avg_random = np.mean(random_returns)
        pctile = sum(1 for r in random_returns if real_return > r) / len(random_returns) * 100

        print(f"  Random entry avg return: {avg_random:+.2f}%")
        print(f"  Strategy beats {pctile:.0f}% of random trials")

        if pctile >= 75:
            print("  [PASS] Strategy significantly outperforms random entries.")
            return True
        elif pctile >= 50:
            print("  [WARN] Strategy only slightly beats random entries.")
            return False
        else:
            print("  [FAIL] Strategy does NOT beat random entries - entry logic adds no value!")
            return False

    print("  [ERROR] Could not run random entry trials.")
    return False


def check_6_out_of_sample(data: pd.DataFrame, symbol: str, holdout_months: int = 6) -> bool:
    """
    Reserve the last N months as a genuine out-of-sample holdout.
    Test exactly once.
    """
    print(f"\n[6] Out-of-Sample Holdout ({holdout_months} months): {symbol}")
    print("-" * 40)

    cutoff = data.index[-1] - pd.DateOffset(months=holdout_months)
    train_data = data[data.index < cutoff]
    test_data = data[data.index >= cutoff]

    if len(test_data) < 100:
        print(f"  [SKIP] Not enough out-of-sample data ({len(test_data)} bars).")
        return False

    print(f"  Train: {train_data.index[0]} to {train_data.index[-1]} ({len(train_data)} bars)")
    print(f"  Test:  {test_data.index[0]} to {test_data.index[-1]} ({len(test_data)} bars)")

    # Train
    bt_train = Backtest(train_data, ORBStrategy, cash=100_000, commission=COMMISSION,
                        exclusive_orders=True, trade_on_close=True)
    train_stats = bt_train.run(or_bars=6, rr_ratio=2.0, min_range_pct=0.0)
    train_ret = train_stats.get("Return [%]", 0)
    train_sharpe = train_stats.get("Sharpe Ratio", 0)

    # Test (out-of-sample, same parameters)
    bt_test = Backtest(test_data, ORBStrategy, cash=100_000, commission=COMMISSION,
                       exclusive_orders=True, trade_on_close=True)
    test_stats = bt_test.run(or_bars=6, rr_ratio=2.0, min_range_pct=0.0)
    test_ret = test_stats.get("Return [%]", 0)
    test_sharpe = test_stats.get("Sharpe Ratio", 0)
    test_trades = test_stats.get("# Trades", 0)

    print(f"  In-sample:     Return={train_ret:+.2f}%, Sharpe={train_sharpe:.3f}")
    print(f"  Out-of-sample: Return={test_ret:+.2f}%, Sharpe={test_sharpe:.3f}, Trades={test_trades}")

    # Check if OOS performance is at least somewhat positive
    if test_ret > 0 and test_sharpe > 0:
        print("  [PASS] Positive out-of-sample performance.")
        return True
    else:
        print("  [WARN] Out-of-sample performance is flat or negative.")
        return False


def run_full_validation(symbol: str = None):
    """Run the complete validation suite on one or all stocks."""
    if symbol:
        csv_files = [DATA_DIR / f"{symbol}_5min.csv"]
    else:
        csv_files = sorted(DATA_DIR.glob("*_5min.csv"))

    if not csv_files:
        print("[ERROR] No data files found. Run data/fetch_historical.py first.")
        sys.exit(1)

    for csv_path in csv_files:
        if not csv_path.exists():
            print(f"[ERROR] File not found: {csv_path}")
            continue

        sym = csv_path.stem.replace("_5min", "")
        data = load_data(csv_path)

        print(f"\n{'='*60}")
        print(f"  VALIDATION SUITE: {sym}")
        print(f"  Data: {len(data)} bars, {data.index[0]} to {data.index[-1]}")
        print(f"{'='*60}")

        # Run the base backtest first
        bt = Backtest(data, ORBStrategy, cash=100_000, commission=COMMISSION,
                      exclusive_orders=True, trade_on_close=True)
        base_stats = bt.run(or_bars=6, rr_ratio=2.0, min_range_pct=0.0)

        checks = {
            "Multi-regime": check_1_multi_regime(data, sym),
            "Trade count": check_2_trade_count(base_stats, sym),
            "Param robustness": check_3_parameter_robustness(data, sym),
            "Walk-forward": check_4_walk_forward(data, sym),
            "Random entry": check_5_random_entry_benchmark(data, sym),
            "Out-of-sample": check_6_out_of_sample(data, sym),
        }

        # Summary
        print(f"\n{'='*60}")
        print(f"  VALIDATION SUMMARY: {sym}")
        print(f"{'='*60}")
        passed = 0
        for name, result in checks.items():
            status = "PASS" if result else "WARN/FAIL"
            print(f"  {name:25s}: {status}")
            if result:
                passed += 1
        print(f"\n  Score: {passed}/{len(checks)} checks passed")

        if passed >= 5:
            print("  VERDICT: Strategy looks robust. Consider moving to Phase 2.")
        elif passed >= 3:
            print("  VERDICT: Strategy shows some promise but needs refinement.")
        else:
            print("  VERDICT: Strategy likely overfitted or lacks edge. Iterate or try another candidate.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run overfitting validation suite")
    parser.add_argument("--symbol", type=str, default=None, help="Validate a single symbol")
    args = parser.parse_args()

    run_full_validation(symbol=args.symbol)

"""Parameter sweep: run the backtest across a grid of params, rank by profit.

This is the optimization engine for "what settings make the most money?". Give
it a list of Ticks (synthetic now, real exported Kalshi data later) and a grid
of parameter values; it runs every combination and returns the configurations
ranked by net P&L per trade (EV) — the bottom-line edge metric.

CLI demo (synthetic data, no external deps):

    python -m engine.backtest.sweep
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Iterable

from engine.backtest.runner import BacktestParams, BacktestRunner, BacktestResult, Tick


def sweep(ticks: list[Tick], base: BacktestParams,
          grid: dict[str, Iterable]) -> list[tuple[BacktestParams, BacktestResult]]:
    """Run every combination in ``grid`` and return (params, result) sorted by
    EV per trade descending (configs that placed no trades sort last)."""
    keys = list(grid.keys())
    runs: list[tuple[BacktestParams, BacktestResult]] = []
    for combo in itertools.product(*(list(grid[k]) for k in keys)):
        params = replace(base, **dict(zip(keys, combo)))
        result = BacktestRunner(params).run(ticks)
        runs.append((params, result))
    runs.sort(
        key=lambda pr: (pr[1].ev_per_trade if pr[1].ev_per_trade is not None else -1e9),
        reverse=True,
    )
    return runs


def _demo() -> None:
    from engine.backtest.synthetic import SynthConfig, generate

    print("Synthetic strategy validation — does the machinery harvest edge net of fees?\n")
    base = BacktestParams(min_edge=0.04, min_model_prob=0.58)
    grid = {"min_edge": [0.02, 0.04, 0.06, 0.10], "min_model_prob": [0.50, 0.58, 0.66]}

    for label, mispricing in [
        ("Efficient market (no edge)", 1.0),
        ("Mild mispricing (market 15% over-vol)", 1.15),
        ("Strong mispricing (market 35% over-vol)", 1.35),
    ]:
        ticks = generate(SynthConfig(mispricing=mispricing, n_windows=400))
        runs = sweep(ticks, base, grid)
        best_params, best = runs[0]
        worst_params, worst = runs[-1]
        print(f"### {label}  (mispricing={mispricing})")
        print(f"  Best config:  min_edge={best_params.min_edge} "
              f"min_model_prob={best_params.min_model_prob}")
        print("   " + best.summary().replace("\n", "\n   "))
        ev = worst.ev_per_trade
        print(f"  Worst config EV/trade: {f'${ev:+.3f}' if ev is not None else '—'} "
              f"(min_edge={worst_params.min_edge}, "
              f"min_model_prob={worst_params.min_model_prob})")
        print()


if __name__ == "__main__":
    _demo()

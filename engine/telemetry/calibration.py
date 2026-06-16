"""Model calibration tracking: Brier score and calibration bands.

Every time we evaluate a market, we record a prediction (model_prob, ticker,
side, timestamp).  When the market settles, we resolve those predictions with
the actual binary outcome.  Over time this gives us:

* Brier score  — mean(model_prob - outcome)^2 across recent N predictions.
  Lower is better; 0.25 is chance (random).
* Calibration bands — for each 0.1-width probability bucket, what fraction of
  predictions actually resolved in that direction?  A well-calibrated model
  should have ~50% realisation in the 0.45–0.55 bucket, ~70% in 0.65–0.75, etc.
* Sharpness — how often does the model make extreme (>0.7 or <0.3) predictions?
  Sharp predictions are valuable only if they are also calibrated.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PredRecord:
    ticker: str
    side: str
    model_prob: float
    predicted_at: float
    outcome: Optional[int] = None    # 1 = resolved YES, 0 = resolved NO
    resolved_at: Optional[float] = None

    @property
    def resolved(self) -> bool:
        return self.outcome is not None

    @property
    def squared_error(self) -> Optional[float]:
        if self.outcome is None:
            return None
        return (self.model_prob - self.outcome) ** 2


class CalibrationTracker:
    """In-memory calibration tracker with a bounded rolling window.

    Parameters
    ----------
    max_records:
        Maximum number of prediction records to keep.  Older entries are
        dropped to avoid unbounded growth.
    dedupe_window_s:
        Suppress duplicate predictions for the same (ticker, side) within
        this many seconds to avoid flooding the record from the eval loop.
    """

    def __init__(self, max_records: int = 2000, dedupe_window_s: float = 60.0):
        self._records: deque[PredRecord] = deque(maxlen=max_records)
        self._last_prediction: dict[str, float] = {}  # key→timestamp
        self.dedupe_window = dedupe_window_s

    # ---- write ----

    def record_prediction(
        self, ticker: str, side: str, model_prob: float, ts: Optional[float] = None
    ) -> None:
        key = f"{ticker}:{side}"
        now = ts or time.time()
        last = self._last_prediction.get(key, 0.0)
        if now - last < self.dedupe_window:
            return
        self._last_prediction[key] = now
        self._records.append(
            PredRecord(ticker=ticker, side=side, model_prob=model_prob, predicted_at=now)
        )

    def resolve(self, ticker: str, up_wins: bool) -> int:
        """Mark all pending predictions for ``ticker`` with the actual outcome.

        Returns the count of records resolved.
        """
        count = 0
        now = time.time()
        for rec in self._records:
            if rec.ticker == ticker and not rec.resolved:
                # "up" side: outcome=1 if up_wins, else 0
                # "down" side: outcome=1 if NOT up_wins (down resolves YES)
                if rec.side == "up":
                    rec.outcome = 1 if up_wins else 0
                else:
                    rec.outcome = 1 if not up_wins else 0
                rec.resolved_at = now
                count += 1
        return count

    # ---- read ----

    def brier_score(self, n: int = 200) -> Optional[float]:
        """Mean squared error over the last ``n`` resolved predictions."""
        resolved = [r for r in self._records if r.resolved][-n:]
        if not resolved:
            return None
        return sum(r.squared_error for r in resolved) / len(resolved)  # type: ignore[arg-type]

    def resolution_count(self) -> int:
        return sum(1 for r in self._records if r.resolved)

    def pending_count(self) -> int:
        return sum(1 for r in self._records if not r.resolved)

    def calibration_bands(self) -> list[dict]:
        """For each 0.1-wide probability bucket, return fraction that resolved YES.

        Returns a list of dicts: {"bucket": "0.4–0.5", "predicted": 0.45,
        "actual": 0.43, "count": 12}.
        """
        from collections import defaultdict
        buckets: dict[int, list[float]] = defaultdict(list)
        for rec in self._records:
            if rec.resolved:
                b = min(int(rec.model_prob * 10), 9)  # 0-9
                buckets[b].append(float(rec.outcome))  # type: ignore[arg-type]

        bands = []
        for b in range(10):
            vals = buckets.get(b, [])
            lo, hi = b / 10, (b + 1) / 10
            bands.append({
                "bucket": f"{lo:.1f}–{hi:.1f}",
                "predicted": round((lo + hi) / 2, 2),
                "actual": round(sum(vals) / len(vals), 3) if vals else None,
                "count": len(vals),
            })
        return bands

    def sharpness(self) -> float:
        """Fraction of predictions with model_prob outside (0.3, 0.7) — 'extreme'."""
        total = len(self._records)
        if total == 0:
            return 0.0
        extreme = sum(
            1 for r in self._records if r.model_prob < 0.3 or r.model_prob > 0.7
        )
        return round(extreme / total, 3)

    def recent_losing_trades(self, n: int = 20) -> list[dict]:
        """Return the last ``n`` resolved records where we were wrong (outcome ≠
        round(model_prob)) — for feeding to the LLM post-mortem."""
        losses = [
            {
                "ticker": r.ticker,
                "side": r.side,
                "model_prob": round(r.model_prob, 3),
                "outcome": r.outcome,
                "error": round((r.model_prob - r.outcome) ** 2, 4),  # type: ignore[operator]
            }
            for r in self._records
            if r.resolved and abs(r.model_prob - r.outcome) > 0.5  # type: ignore[operator]
        ]
        return losses[-n:]

    def summary(self) -> dict:
        return {
            "brier_score": self.brier_score(),
            "resolution_count": self.resolution_count(),
            "pending_count": self.pending_count(),
            "sharpness": self.sharpness(),
            "bands": self.calibration_bands(),
        }

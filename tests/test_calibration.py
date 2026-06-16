"""Tests for the calibration tracker."""

import pytest
from engine.telemetry.calibration import CalibrationTracker


def make_tracker(**kw):
    return CalibrationTracker(
        dedupe_window_s=kw.pop("dedupe_window_s", 0),  # disable dedupe in tests
        **kw,
    )


def test_empty_brier_returns_none():
    t = make_tracker()
    assert t.brier_score() is None


def test_prediction_and_resolve():
    t = make_tracker()
    t.record_prediction("KXBTC-1", "up", 0.8)
    resolved = t.resolve("KXBTC-1", up_wins=True)
    assert resolved == 1
    # outcome=1 for "up" when up_wins=True
    rec = list(t._records)[0]
    assert rec.outcome == 1
    assert rec.resolved is True


def test_down_side_resolves_opposite():
    t = make_tracker()
    t.record_prediction("KXBTC-1", "down", 0.7)
    t.resolve("KXBTC-1", up_wins=True)
    rec = list(t._records)[0]
    assert rec.outcome == 0  # down bet lost when up_wins


def test_brier_perfect_calibration():
    t = make_tracker()
    # Predict 1.0, outcome 1 → error = 0
    t.record_prediction("T", "up", 1.0)
    t.resolve("T", up_wins=True)
    assert t.brier_score() == pytest.approx(0.0)


def test_brier_worst_calibration():
    t = make_tracker()
    # Predict 1.0, outcome 0 → error = 1
    t.record_prediction("T", "up", 1.0)
    t.resolve("T", up_wins=False)
    assert t.brier_score() == pytest.approx(1.0)


def test_brier_random_calibration():
    t = make_tracker()
    # Predict 0.5 for each → squared error = 0.25 regardless
    for i in range(4):
        t.record_prediction(f"T{i}", "up", 0.5)
        t.resolve(f"T{i}", up_wins=i % 2 == 0)
    bs = t.brier_score()
    assert bs == pytest.approx(0.25)


def test_calibration_bands():
    t = make_tracker()
    # Three predictions in the 0.7–0.8 bucket, all resolve YES
    for i in range(3):
        t.record_prediction(f"T{i}", "up", 0.75)
        t.resolve(f"T{i}", up_wins=True)
    bands = t.calibration_bands()
    bucket = next(b for b in bands if b["bucket"] == "0.7–0.8")
    assert bucket["count"] == 3
    assert bucket["actual"] == pytest.approx(1.0)


def test_recent_losing_trades():
    t = make_tracker()
    # One clear loss: model says 0.9 but resolves 0
    t.record_prediction("T", "up", 0.9)
    t.resolve("T", up_wins=False)
    losses = t.recent_losing_trades()
    assert len(losses) == 1
    assert losses[0]["model_prob"] == pytest.approx(0.9)
    assert losses[0]["outcome"] == 0


def test_resolution_and_pending_counts():
    t = make_tracker()
    t.record_prediction("A", "up", 0.6)
    t.record_prediction("B", "up", 0.4)
    assert t.pending_count() == 2
    assert t.resolution_count() == 0
    t.resolve("A", up_wins=True)
    assert t.resolution_count() == 1
    assert t.pending_count() == 1


def test_sharpness():
    t = make_tracker()
    t.record_prediction("A", "up", 0.8)   # extreme
    t.record_prediction("B", "up", 0.5)   # not extreme
    assert t.sharpness() == pytest.approx(0.5)


def test_dedupe_suppresses_duplicate_predictions():
    t = CalibrationTracker(dedupe_window_s=60.0)
    t.record_prediction("T", "up", 0.6)
    t.record_prediction("T", "up", 0.7)  # same key, within window → suppressed
    assert len(t._records) == 1


def test_summary_keys_present():
    t = make_tracker()
    s = t.summary()
    for k in ("brier_score", "resolution_count", "pending_count", "sharpness", "bands"):
        assert k in s

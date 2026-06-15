"""Tests for the fair-value pricing model."""

import math

from engine.pricing.model import VolEstimator, fair_prob, prob_above


def test_at_the_money_is_half():
    # Spot == strike, with vol and time, P(above) ~ 0.5 (slightly below due to
    # the -0.5*sigma^2 drift term).
    p = prob_above(spot=100.0, strike=100.0, sigma_annual=0.5, tau_seconds=900)
    assert 0.45 < p < 0.5


def test_deep_in_the_money():
    p = prob_above(spot=120.0, strike=100.0, sigma_annual=0.5, tau_seconds=900)
    assert p > 0.99


def test_deep_out_of_the_money():
    p = prob_above(spot=80.0, strike=100.0, sigma_annual=0.5, tau_seconds=900)
    assert p < 0.01


def test_tau_zero_pins_to_spot():
    # No time left: deterministic pin around the strike.
    assert prob_above(100.01, 100.0, 0.5, 0.0) == 1.0
    assert prob_above(99.99, 100.0, 0.5, 0.0) == 0.0


def test_up_and_down_complement():
    up = fair_prob("up", 105.0, 100.0, 0.6, 600)
    down = fair_prob("down", 105.0, 100.0, 0.6, 600)
    assert math.isclose(up + down, 1.0, abs_tol=1e-9)


def test_vol_estimator_positive_with_movement():
    est = VolEstimator(lookback_seconds=900)
    price = 100.0
    for i in range(60):
        price *= 1.0 + (0.001 if i % 2 == 0 else -0.0008)
        est.add(float(i), price)
    assert est.sigma_annual() > 0.0


def test_vol_estimator_insufficient_data():
    est = VolEstimator()
    est.add(0.0, 100.0)
    assert est.sigma_annual() == 0.0

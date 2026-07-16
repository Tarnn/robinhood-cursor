"""Golden Black-Scholes values (independently computed) + EV behavior under cost drag."""

from __future__ import annotations

import math

import pytest
from conftest import NOW, make_leg, make_ticket

from rh_options import pop_ev
from rh_options.models import Structure

TODAY = NOW.date()


def test_golden_prob_above() -> None:
    p = pop_ev.prob_beyond(spot=100, strike=95, iv=0.20, dte_years=30 / 365, rate=0.04, above=True)
    assert p == pytest.approx(0.82206, abs=1e-5)


def test_golden_prob_short_put_sofi() -> None:
    p = pop_ev.prob_beyond(
        spot=17.9, strike=16, iv=0.65, dte_years=35 / 365, rate=0.04, above=True
    )
    assert p == pytest.approx(0.68293, abs=1e-5)


def test_golden_prob_below_call() -> None:
    p = pop_ev.prob_beyond(
        spot=100, strike=105, iv=0.20, dte_years=30 / 365, rate=0.04, above=False
    )
    assert p == pytest.approx(0.794533, abs=1e-5)


def test_above_and_below_sum_to_one() -> None:
    kwargs = {"spot": 50.0, "strike": 48.0, "iv": 0.4, "dte_years": 0.1, "rate": 0.04}
    total = pop_ev.prob_beyond(above=True, **kwargs) + pop_ev.prob_beyond(above=False, **kwargs)
    assert total == pytest.approx(1.0)


def test_higher_strike_lowers_prob_above() -> None:
    ps = [
        pop_ev.prob_beyond(spot=100, strike=k, iv=0.3, dte_years=0.1, rate=0.04, above=True)
        for k in (90, 95, 100, 105)
    ]
    assert ps == sorted(ps, reverse=True)


def test_zero_inputs_raise() -> None:
    for bad in ({"iv": 0.0}, {"dte_years": 0.0}, {"spot": 0.0}, {"strike": -1.0}):
        kwargs = {"spot": 100.0, "strike": 95.0, "iv": 0.2, "dte_years": 0.1, "rate": 0.04}
        kwargs.update(bad)
        with pytest.raises(ValueError):
            pop_ev.prob_beyond(above=True, **kwargs)


def test_analyze_golden_ticket() -> None:
    report = pop_ev.analyze(make_ticket(), iv=0.65, today=TODAY)
    assert report.pop_short_strike == pytest.approx(0.68293, abs=1e-4)
    assert report.credit_dollars == 27.0
    assert report.max_loss_dollars == 73.0
    # 4 executions x $0.04 + 2 contracts TAF on sells
    assert report.fees_round_trip == pytest.approx(0.17, abs=0.01)
    # half-spread both legs, in and out: (0.025 + 0.025) * 2 * 100 = $10
    assert report.slippage_round_trip == pytest.approx(10.0)
    assert report.breakeven_win_rate == pytest.approx(73 / 100, abs=1e-4)


def test_ev_sign_flips_as_slippage_grows() -> None:
    tight = make_ticket()
    wide_legs = [
        make_leg(bid=0.53, ask=0.66),  # same mids, much wider markets
        make_leg(action="buy", strike=15.0, bid=0.26, ask=0.39, delta=-0.15),
    ]
    wide = make_ticket(legs=wide_legs)
    assert wide.credit_mid == pytest.approx(tight.credit_mid)
    r_tight = pop_ev.analyze(tight, iv=0.65, today=TODAY)
    r_wide = pop_ev.analyze(wide, iv=0.65, today=TODAY)
    assert r_wide.slippage_round_trip > r_tight.slippage_round_trip
    assert r_wide.ev_managed_net < r_tight.ev_managed_net
    assert r_wide.verdict != "positive-EV under assumptions"


def test_iron_condor_rejected() -> None:
    t = make_ticket()
    ic = make_ticket(structure=Structure.IRON_CONDOR, legs=t.legs)
    with pytest.raises(ValueError, match="verticals"):
        pop_ev.analyze(ic, iv=0.65, today=TODAY)


def test_norm_cdf_symmetry() -> None:
    assert pop_ev.norm_cdf(0.0) == pytest.approx(0.5)
    for x in (0.5, 1.0, 2.33):
        assert pop_ev.norm_cdf(x) + pop_ev.norm_cdf(-x) == pytest.approx(1.0)
    assert pop_ev.norm_cdf(1.0) == pytest.approx(0.5 * (1 + math.erf(1 / math.sqrt(2))))

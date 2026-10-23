from edgebot.analytics.score import score_volatility
from edgebot.config import AnalyticsGates


def test_volatility_sweet_spot():
    gates = AnalyticsGates(min_atr_pct=0.004, max_atr_pct=0.045)
    mid = score_volatility(0.02, gates)
    low = score_volatility(0.001, gates)
    high = score_volatility(0.08, gates)
    assert mid > 0.7
    assert low == 0.0
    assert high == 0.0

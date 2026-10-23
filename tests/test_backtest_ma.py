import pandas as pd

from edgebot.backtest.engine import simulate_signals, summarize_trades
from edgebot.bybit.demo_data import demo_klines
from edgebot.strategies.ema_ma import HEAVY_DEFAULT, generate_signals


def test_heavy_signals_and_sim():
    entry = demo_klines(400, seed=1)
    htf = demo_klines(200, seed=2)
    sigs = generate_signals(entry, htf, HEAVY_DEFAULT, allow_short=True)
    assert isinstance(sigs, pd.DataFrame)
    trades = simulate_signals(entry, sigs)
    metrics = summarize_trades(trades)
    assert "expectancy_r" in metrics
    assert metrics["trades"] >= 0

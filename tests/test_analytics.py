"""Kiểm thử công thức rủi ro/lợi suất, tối ưu danh mục và đối soát mart dbt với NumPy/pandas.

Phần đối soát mart đọc DuckDB local (warehouse/vnstock.duckdb) và bị bỏ qua nếu chưa dựng kho.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analytics import portfolio_optimizer as po
from analytics import risk

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "warehouse" / "vnstock.duckdb"


# ------------------------------------------------------------------ công thức trên dữ liệu tổng hợp
def test_annualized_return_and_vol_known_values():
    r = pd.Series([0.01] * 252)
    assert risk.annualized_return(r) == pytest.approx(1.01 ** 252 - 1)
    assert risk.annualized_volatility(r) == pytest.approx(0.0)


def test_max_drawdown_known():
    assert risk.max_drawdown(pd.Series([100, 120, 90, 110])) == pytest.approx(90 / 120 - 1)


def test_var_is_positive_loss_threshold():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0, 0.01, 2000))
    assert risk.var_historical(r) == pytest.approx(-np.quantile(r, 0.05))
    assert risk.var_historical(r) > 0


def test_beta_uses_common_days_only():
    idx = pd.date_range("2024-01-01", periods=100, freq="B")
    bench = pd.Series(np.random.default_rng(1).normal(0, 0.01, 100), index=idx)
    stock = 1.5 * bench                       # beta = 1.5 chính xác
    b, n = risk.beta(stock.iloc[:80], bench.iloc[20:])   # chỉ 60 ngày giao nhau
    assert n == 60 and b == pytest.approx(1.5)
    assert np.isnan(risk.beta(stock.iloc[:10], bench.iloc[5:])[0])  # quá ít ngày chung


def test_sharpe_needs_positive_vol():
    assert np.isnan(risk.sharpe(pd.Series([0.001] * 100), 0.04))


# ------------------------------------------------------------------ tối ưu danh mục
@pytest.fixture
def rets():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2022-01-03", periods=500, freq="B")
    base = rng.normal(0.0004, 0.01, 500)
    data = {f"S{i}": 0.5 * base + rng.normal(0.0002 * i, 0.006 + 0.002 * i, 500) for i in range(5)}
    return pd.DataFrame(data, index=idx)


@pytest.mark.parametrize("method", po.METHODS)
def test_weights_satisfy_constraints(rets, method):
    train, _ = po.split_train_test(rets)
    res = po.optimize(train, method, max_weight=0.35)
    w = res.weights.to_numpy()
    assert w.sum() == pytest.approx(1.0, abs=1e-6)
    assert w.min() >= -1e-8 and w.max() <= 0.35 + 1e-6


def test_min_variance_not_worse_than_equal_weight_in_sample(rets):
    train, _ = po.split_train_test(rets)
    cov = train.cov().to_numpy()
    ew = po.optimize(train, "equal_weight", 0.5).weights.to_numpy()
    mv = po.optimize(train, "min_variance", 0.5).weights.to_numpy()
    assert mv @ cov @ mv <= ew @ cov @ ew + 1e-12


def test_split_is_chronological_and_no_overlap(rets):
    train, test = po.split_train_test(rets, 0.3)
    assert train.index.max() < test.index.min()
    assert len(train) + len(test) == len(rets)


def test_weights_depend_only_on_train(rets):
    """Đổi dữ liệu TEST không được làm thay đổi trọng số (không rò rỉ)."""
    train, test = po.split_train_test(rets)
    w1 = po.optimize(train, "max_sharpe", 0.4).weights
    tampered = rets.copy()
    tampered.loc[test.index] = tampered.loc[test.index] * 10
    train2, _ = po.split_train_test(tampered)
    w2 = po.optimize(train2, "max_sharpe", 0.4).weights
    pd.testing.assert_series_equal(w1, w2)


def test_infeasible_max_weight_raises(rets):
    with pytest.raises(po.PortfolioError, match="Bất khả thi"):
        po.validate_constraints(3, 0.30)


def test_too_few_assets_or_history_raise(rets):
    with pytest.raises(po.PortfolioError):
        po.validate_constraints(1, 1.0)
    with pytest.raises(po.PortfolioError, match="phiên huấn luyện"):
        po.split_train_test(rets.iloc[:50])


def test_singular_covariance_raises(rets):
    train, _ = po.split_train_test(rets)
    train = train.assign(DUP=train["S0"])
    with pytest.raises(po.PortfolioError, match="suy biến"):
        po.optimize(train, "min_variance", 0.5)


def test_efficient_frontier_is_valid(rets):
    train, _ = po.split_train_test(rets)
    ef = po.efficient_frontier(train, 0.5)
    assert (ef.volatility > 0).all() and len(ef) >= 3


# ------------------------------------------------------------------ đối soát mart dbt với NumPy/pandas
@pytest.fixture(scope="module")
def con():
    if not DB.is_file():
        pytest.skip("Chưa có kho DuckDB local")
    import duckdb
    c = duckdb.connect(str(DB), read_only=True)
    try:
        c.execute("select 1 from gold.mart_risk_metrics limit 1")
    except Exception:
        pytest.skip("Chưa dựng mart_risk_metrics (chạy dbt build)")
    yield c
    c.close()


@pytest.mark.parametrize("symbol,window", [("FPT", 252), ("VCB", 120), ("HPG", 60)])
def test_risk_mart_matches_pandas(con, symbol, window):
    px = con.execute("select trade_date, close from gold.fact_price_daily where symbol = ? order by trade_date",
                     [symbol]).df().set_index("trade_date").close
    idx = con.execute("select trade_date, close from gold.fact_index_daily where index_code='VNINDEX' "
                      "order by trade_date").df().set_index("trade_date").close
    r = risk.daily_returns(px).iloc[-window:]
    prices = px.loc[r.index]
    bench = risk.daily_returns(idx)
    m = con.execute("select * from gold.mart_risk_metrics where symbol=? and window_days=?", [symbol, window]).df().iloc[0]
    assert m.n_obs == len(r)
    assert m.annualized_return == pytest.approx(risk.annualized_return(r), rel=1e-9)
    assert m.annualized_volatility == pytest.approx(risk.annualized_volatility(r), rel=1e-9)
    assert m.max_drawdown == pytest.approx(risk.max_drawdown(prices), rel=1e-9)
    assert m.var95_daily == pytest.approx(risk.var_historical(r), rel=1e-9)
    b, n = risk.beta(r, bench)
    assert m.n_obs_beta == n
    assert m.beta == pytest.approx(b, rel=1e-9)
    assert m.sharpe == pytest.approx(risk.sharpe(r, m.risk_free_rate_annual), rel=1e-9)


def test_correlation_mart_matches_pandas_and_is_valid(con):
    px = con.execute("select trade_date, symbol, close from gold.fact_price_daily").df()
    wide = px.pivot(index="trade_date", columns="symbol", values="close").sort_index()
    rets = wide.pct_change(fill_method=None)
    last = rets.dropna(how="all").index[-252:]
    pair = con.execute("select * from gold.mart_correlation_pairs where window_days=252 and symbol_a='FPT' "
                       "and symbol_b='VCB'").df().iloc[0]
    j = rets.loc[last, ["FPT", "VCB"]].dropna()
    assert pair.n_obs == len(j)
    assert pair.correlation == pytest.approx(j.corr().iloc[0, 1], rel=1e-9)
    allp = con.execute("select correlation, n_obs, window_days from gold.mart_correlation_pairs").df()
    assert allp.correlation.dropna().between(-1 - 1e-9, 1 + 1e-9).all()
    assert (allp.n_obs <= allp.window_days).all()


def test_return_summary_reconciles(con):
    s = con.execute("select * from gold.mart_return_summary where symbol='FPT' and period_type='ALL'").df().iloc[0]
    px = con.execute("select close from gold.fact_price_daily where symbol='FPT' order by trade_date").df().close
    assert s.price_return == pytest.approx(px.iloc[-1] / px.iloc[0] - 1)
    m = con.execute("select * from gold.mart_return_summary where symbol='FPT' and period_type='MONTH' "
                    "order by period_label").df()
    assert m.price_return.notna().all() and m.cagr.isna().all()      # CAGR không áp cho kỳ tháng


def test_buy_and_hold_curve_matches_manual(rets):
    train, test = po.split_train_test(rets)
    w = po.optimize(train, "equal_weight", 0.5).weights
    curve = po.buy_and_hold_curve(test, w, fee_bps=10)
    manual = 100 * 0.999 * sum(w[c] * (1 + test[c]).prod() for c in w.index)
    assert curve.iloc[-1] == pytest.approx(manual)
    with pytest.raises(po.PortfolioError):
        po.buy_and_hold_curve(test, w, fee_bps=-1)

"""Công thức rủi ro - lợi suất thuần pandas/numpy, dùng để đối soát mart dbt và cho Portfolio Lab.

Quy ước: lợi suất ngày là PRICE return (close_t / close_{t-1} - 1), 252 phiên/năm.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def daily_returns(close: pd.Series) -> pd.Series:
    return close.pct_change().dropna()


def annualized_return(returns: pd.Series) -> float:
    """(Π(1+r))^(252/n) - 1; NaN nếu không đủ quan sát."""
    r = pd.Series(returns).dropna()
    if len(r) < 2:
        return float("nan")
    return float(np.prod(1 + r.to_numpy()) ** (TRADING_DAYS / len(r)) - 1)


def annualized_volatility(returns: pd.Series) -> float:
    r = pd.Series(returns).dropna()
    return float(r.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(r) >= 2 else float("nan")


def max_drawdown(close: pd.Series) -> float:
    c = pd.Series(close).dropna()
    return float((c / c.cummax() - 1).min()) if len(c) else float("nan")


def var_historical(returns: pd.Series, level: float = 0.95) -> float:
    """Ngưỡng lỗ một ngày ước lượng từ lịch sử (số dương). Không phải mức lỗ tối đa."""
    r = pd.Series(returns).dropna()
    return float(-np.quantile(r.to_numpy(), 1 - level)) if len(r) else float("nan")


def beta(returns: pd.Series, bench: pd.Series, min_obs: int = 30) -> tuple[float, int]:
    """Beta = Cov/Var trên NGÀY CHUNG (inner join theo index). Trả (beta, số ngày chung)."""
    j = pd.concat([returns, bench], axis=1, join="inner").dropna()
    if len(j) < min_obs or j.iloc[:, 1].var(ddof=1) <= 0:
        return float("nan"), len(j)
    return float(j.cov().iloc[0, 1] / j.iloc[:, 1].var(ddof=1)), len(j)


def sharpe(returns: pd.Series, rf_annual: float) -> float:
    vol = annualized_volatility(returns)
    if np.isnan(vol) or vol <= 1e-12:
        return float("nan")
    return float((annualized_return(returns) - rf_annual) / vol)

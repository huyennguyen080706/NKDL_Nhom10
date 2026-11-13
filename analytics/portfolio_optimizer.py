"""Tối ưu danh mục long-only (Equal Weight, Minimum Variance, Maximum Sharpe) với tách train/test theo thời gian.

Nguyên tắc chống rò rỉ: trọng số chỉ ước lượng từ phần TRAIN; phần TEST chỉ dùng để đánh giá.
Đây là mô phỏng nghiên cứu trên lợi suất giá, không phải khuyến nghị đầu tư.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .risk import TRADING_DAYS

METHODS = ("equal_weight", "min_variance", "max_sharpe")
MIN_TRAIN_OBS = 60
MIN_TEST_OBS = 20


class PortfolioError(ValueError):
    """Lỗi đầu vào / solver có thông điệp cho người dùng."""


@dataclass
class Result:
    method: str
    weights: pd.Series
    train_return: float          # lợi suất kỳ vọng quy năm (in-sample, chỉ để tham khảo)
    train_volatility: float


def split_train_test(returns: pd.DataFrame, test_fraction: float = 0.3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cắt theo thời gian: train = phần đầu, test = phần sau. Chỉ giữ ngày CHUNG của mọi mã."""
    r = returns.dropna(how="any").sort_index()
    if not 0.1 <= test_fraction <= 0.6:
        raise PortfolioError("Tỷ lệ test phải nằm trong khoảng 10% đến 60%.")
    n_test = int(round(len(r) * test_fraction))
    train, test = r.iloc[: len(r) - n_test], r.iloc[len(r) - n_test:]
    if len(train) < MIN_TRAIN_OBS:
        raise PortfolioError(f"Chỉ có {len(train)} phiên huấn luyện chung; cần ít nhất {MIN_TRAIN_OBS}. "
                             "Hãy bớt mã niêm yết ngắn, mở rộng khoảng ngày hoặc giảm tỷ lệ test.")
    if len(test) < MIN_TEST_OBS:
        raise PortfolioError(f"Chỉ có {len(test)} phiên kiểm tra; cần ít nhất {MIN_TEST_OBS}.")
    if not train.index.max() < test.index.min():
        raise PortfolioError("Train và test giao nhau về thời gian.")
    return train, test


def validate_constraints(n_assets: int, max_weight: float) -> None:
    if not 2 <= n_assets <= 10:
        raise PortfolioError("Chọn từ 2 đến 10 mã.")
    if max_weight <= 0 or max_weight > 1:
        raise PortfolioError("Trọng số tối đa phải trong (0, 100%].")
    if n_assets * max_weight < 1 - 1e-9:
        raise PortfolioError(f"Bất khả thi: {n_assets} mã × {max_weight:.0%} < 100%. "
                             "Tăng trọng số tối đa hoặc chọn thêm mã.")


def _check(weights: np.ndarray, max_weight: float) -> None:
    if abs(weights.sum() - 1) > 1e-6 or weights.min() < -1e-8 or weights.max() > max_weight + 1e-6:
        raise PortfolioError("Nghiệm không thỏa ràng buộc (tổng = 1, long-only, trần trọng số).")


def _moments(train: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    mu = train.mean().to_numpy() * TRADING_DAYS                       # xấp xỉ lợi suất kỳ vọng quy năm
    cov = train.cov().to_numpy() * TRADING_DAYS
    n = train.shape[1]
    if not (np.isfinite(cov).all() and np.isfinite(mu).all()):
        raise PortfolioError("Ma trận hiệp phương sai chứa giá trị không hợp lệ.")
    if np.linalg.matrix_rank(cov) < n:
        raise PortfolioError("Ma trận hiệp phương sai suy biến (các mã gần như phụ thuộc tuyến tính).")
    return mu, cov


def optimize(train: pd.DataFrame, method: str, max_weight: float = 0.35, rf_annual: float = 0.04) -> Result:
    """Ước lượng trọng số CHỈ từ dữ liệu train."""
    if method not in METHODS:
        raise PortfolioError(f"Phương pháp không hỗ trợ: {method}")
    n = train.shape[1]
    validate_constraints(n, max_weight)
    mu, cov = _moments(train)

    if method == "equal_weight":
        w = np.full(n, 1.0 / n)
        if w.max() > max_weight + 1e-9:
            raise PortfolioError("Equal Weight vượt trần trọng số; tăng trọng số tối đa.")
    else:
        if method == "min_variance":
            def obj(x):
                return float(x @ cov @ x)
        else:
            def obj(x):
                vol = np.sqrt(max(x @ cov @ x, 1e-18))
                return -float((x @ mu - rf_annual) / vol)
        res = minimize(obj, np.full(n, 1.0 / n), method="SLSQP", bounds=[(0.0, max_weight)] * n,
                       constraints=[{"type": "eq", "fun": lambda x: x.sum() - 1}],
                       options={"maxiter": 500, "ftol": 1e-12})
        if not res.success:
            raise PortfolioError(f"Solver không hội tụ: {res.message}")
        w = np.clip(res.x, 0, max_weight)
        w = w / w.sum()
    _check(w, max_weight)
    return Result(method, pd.Series(w, index=train.columns), float(w @ mu), float(np.sqrt(w @ cov @ w)))


def efficient_frontier(train: pd.DataFrame, max_weight: float = 0.35, points: int = 25) -> pd.DataFrame:
    """Biên hiệu quả long-only (in-sample, trên train): mỗi mức lợi suất mục tiêu, tối thiểu hóa phương sai."""
    n = train.shape[1]
    validate_constraints(n, max_weight)
    mu, cov = _moments(train)
    mv = optimize(train, "min_variance", max_weight)
    lo = float(mv.weights.to_numpy() @ mu)
    order, left, hi_w = np.argsort(-mu), 1.0, np.zeros(n)   # lợi suất cao nhất khả thi dưới trần trọng số
    for i in order:
        hi_w[i] = min(max_weight, left)
        left -= hi_w[i]
    hi = float(hi_w @ mu)
    rows = []
    for target in np.linspace(lo, hi, points):
        res = minimize(lambda x: float(x @ cov @ x), np.full(n, 1.0 / n), method="SLSQP",
                       bounds=[(0.0, max_weight)] * n,
                       constraints=[{"type": "eq", "fun": lambda x: x.sum() - 1},
                                    {"type": "eq", "fun": lambda x, t=target: x @ mu - t}],
                       options={"maxiter": 300, "ftol": 1e-12})
        if res.success:
            rows.append({"return": float(res.x @ mu), "volatility": float(np.sqrt(res.x @ cov @ res.x))})
    if len(rows) < 3:
        raise PortfolioError("Không dựng được biên hiệu quả ổn định với dữ liệu này.")
    return pd.DataFrame(rows)


def equity_curve(returns: pd.DataFrame | pd.Series, weights: pd.Series | None = None) -> pd.Series:
    """Giá trị danh mục chuẩn hóa 100 (rebalance hằng ngày về đúng trọng số, chưa tính phí)."""
    r = returns if weights is None else returns[weights.index] @ weights
    return 100 * (1 + r).cumprod()


def buy_and_hold_curve(returns: pd.DataFrame, weights: pd.Series, fee_bps: float = 0.0) -> pd.Series:
    """Mua một lần đầu kỳ test theo trọng số rồi giữ (không cân bằng lại), chuẩn hóa 100.

    fee_bps: phí một chiều khi mua (điểm cơ bản). Giá trị danh mục = 100 × (1 - phí) × Σ w_i × Π(1 + r_i).
    """
    if fee_bps < 0 or fee_bps > 500:
        raise PortfolioError("Phí giả định phải trong khoảng 0 đến 500 điểm cơ bản.")
    growth = (1 + returns[weights.index]).cumprod()
    return 100 * (1 - fee_bps / 10_000) * (growth @ weights)

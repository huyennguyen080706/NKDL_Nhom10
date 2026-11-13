# VNStock Intelligence 2.0: giao diện Fox Stocks Light và phân tích rủi ro

## Thay đổi
- Giao diện: theme sáng lavender (`#F8F6FF`, tím `#6425FE`, thẻ pastel mint/vàng/xanh), font Inter, CSS có phạm vi nhỏ tại `app/styles/theme.css`, thành phần dùng chung `app/components/ui.py`.
- 6 trang (điều hướng `st.navigation` trong `app/streamlit_app.py`): Market Overview, Stock Explorer (thêm SMA200, bật/tắt khối lượng và RSI), Risk & Correlation (mới), Financials & Signals, Portfolio Lab (mới), Data Pipeline (đường dẫn cũ `/Pipeline_Health` được giữ).
- Mart Gold mới (dbt, chạy được trên DuckDB và BigQuery): `mart_return_summary`, `mart_risk_metrics`, `mart_correlation_pairs`, kèm dbt test (grain, khoảng giá trị, n_obs).
- `analytics/`: công thức rủi ro và tối ưu danh mục bằng pandas/numpy/scipy để đối soát mart và dùng cho Portfolio Lab.
- Giữ nguyên: ingestion, Bronze/Silver, các mart và SQL cũ.

## Công thức (price return, 252 phiên/năm)
| Chỉ số | Định nghĩa |
|---|---|
| Lợi suất quy năm | (Π(1+r))^(252/n) − 1 |
| Biến động quy năm | stddev_samp(r) × √252 |
| Max drawdown | min(P/running_max − 1) trong cửa sổ |
| VaR95 (1 ngày) | −phân vị 5% của lợi suất ngày (ngưỡng lỗ ước lượng, không phải mức lỗ tối đa) |
| Beta | Cov(r, r_VNIndex)/Var(r_VNIndex) trên ngày chung; NULL nếu dưới 30 ngày chung |
| Sharpe | (lợi suất quy năm − rf)/biến động; rf = `risk_free_rate_annual` (mặc định 4%, giả định) |
| Tương quan | Pearson trên ngày chung của cặp, cửa sổ 60/120/252 phiên; `LOW_OBS` khi n_obs < 60 |

## Giới hạn dữ liệu
Giá chưa xác minh điều chỉnh cổ tức nên chỉ gọi price return; VN-Index chỉ từ 28/10/2022; báo cáo tài chính 15 mã, 4 quý, kỳ 2025-Q4 nghi vấn; không có ngày công bố báo cáo tài chính nên không backtest theo báo cáo; chưa có bảng phân ngành nên heatmap theo mã; cảnh báo là tín hiệu minh họa.

## Portfolio Lab
Long-only, 2–10 mã, tổng trọng số 100%, trần trọng số (mặc định 35%, báo lỗi nếu n × trần < 100%). Trọng số (Equal Weight, Minimum Variance, Maximum Sharpe qua SLSQP) chỉ ước lượng từ giai đoạn TRAIN; giai đoạn TEST phía sau chỉ để đánh giá, so với VN-Index trên ngày chung. Mô phỏng mua một lần và giữ, có phí giả định; nhãn "Research simulation · price-only returns".

## Chạy và kiểm thử
```bash
python scripts/run_pipeline.py --skip-bronze     # dbt build + kiểm chứng
python -m pytest tests -q                         # gồm đối soát mart với NumPy/pandas
streamlit run app/streamlit_app.py
```

## Hoàn tác
Giao diện cũ nằm ở commit `256e79d`. Ba mart mới là bảng bổ sung, xóa được mà không ảnh hưởng mart cũ.

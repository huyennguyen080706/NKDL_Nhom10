-- Fact giá cổ phiếu. Grain: 1 mã / 1 ngày giao dịch (ticker_key + date_key).
-- Loại bản ghi không dùng được (giá <= 0/NULL, khối lượng âm). Bản ghi lệch bao OHLC vẫn giữ
-- (close còn dùng được) kèm cờ is_ohlc_consistent; mọi sai lệch đều nằm ở silver.dq_issue_log.
select
    t.ticker_key,
    {{ date_key('p.trade_date') }}                            as date_key,
    p.symbol,
    p.trade_date,
    p.open,
    p.high,
    p.low,
    p.close,
    p.volume,
    -- Giá trị giao dịch ước tính (tỷ đồng) = close (nghìn đồng) * khối lượng / 1e6
    p.close * p.volume / 1000000.0                            as traded_value_bn_vnd_est,
    p.is_ohlc_consistent,
    p.batch_id
from {{ ref('stg_price_daily') }} p
inner join {{ ref('dim_ticker') }} t on t.symbol = p.symbol
where p.is_price_positive and p.is_volume_valid

-- Fact chỉ số thị trường. Grain: 1 chỉ số / 1 ngày giao dịch.
select
    i.index_code,
    {{ date_key('i.trade_date') }}                            as date_key,
    i.trade_date,
    i.open,
    i.high,
    i.low,
    i.close,
    i.volume,
    i.is_ohlc_consistent,
    i.batch_id
from {{ ref('stg_index_daily') }} i
-- Giữ cả phiên lệch bao OHLC (vd. VNINDEX 15/05/2023 có close < low ở nguồn) để chuỗi lợi suất không đứt.
where i.is_price_positive and i.is_volume_valid

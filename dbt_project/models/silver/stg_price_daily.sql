-- Giá cổ phiếu theo ngày đã chuẩn hóa. Grain: 1 mã / 1 ngày giao dịch.
-- `time` của nguồn là mốc 07:00 giờ Việt Nam (= 00:00 UTC) -> trade_date lấy theo giờ Việt Nam.
-- Giá ở đơn vị nghìn đồng như nguồn trả về (chưa xác minh điều chỉnh cổ tức/chia tách).
with src as (

    select
        upper(trim(symbol))                                   as symbol,
        {{ vn_date(adapter.quote('time')) }}                  as trade_date,
        {{ adapter.quote('time') }}                           as source_time,
        cast(open as {{ type_double() }})                     as open,
        cast(high as {{ type_double() }})                     as high,
        cast(low as {{ type_double() }})                      as low,
        cast(close as {{ type_double() }})                    as close,
        cast(volume as {{ dbt.type_bigint() }})               as volume,
        _source                                               as source,
        _batch_id                                             as batch_id,
        _source_file                                          as source_file,
        _extracted_at                                         as extracted_at,
        _ingested_at                                          as ingested_at
    from {{ source('bronze', 'price_daily_raw') }}

),

ranked as (

    -- Nhiều batch có thể chứa cùng khóa (nạp lại có overlap): giữ bản trích xuất mới nhất.
    select
        *,
        row_number() over (
            partition by symbol, trade_date
            order by extracted_at desc, ingested_at desc
        ) as rn,
        count(*) over (partition by symbol, trade_date) as version_count
    from src
    where symbol is not null and trade_date is not null

)

select
    symbol,
    trade_date,
    source_time,
    open,
    high,
    low,
    close,
    volume,
    'nghin_vnd'                                               as price_unit,
    coalesce(open > 0 and high > 0 and low > 0 and close > 0, false) as is_price_positive,
    coalesce(high >= low and high >= open and high >= close
             and low <= open and low <= close, false)         as is_ohlc_consistent,
    coalesce(volume >= 0, false)                              as is_volume_valid,
    version_count,
    source,
    batch_id,
    source_file,
    extracted_at,
    ingested_at
from ranked
where rn = 1

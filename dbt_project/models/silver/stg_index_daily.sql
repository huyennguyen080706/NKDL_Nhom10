-- Chỉ số thị trường theo ngày đã chuẩn hóa. Grain: 1 chỉ số / 1 ngày giao dịch.
with src as (

    select
        upper(trim(symbol))                                   as index_code,
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
    from {{ source('bronze', 'index_daily_raw') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by index_code, trade_date
            order by extracted_at desc, ingested_at desc
        ) as rn,
        count(*) over (partition by index_code, trade_date) as version_count
    from src
    where index_code is not null and trade_date is not null

)

select
    index_code,
    trade_date,
    source_time,
    open,
    high,
    low,
    close,
    volume,
    'diem'                                                    as value_unit,
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

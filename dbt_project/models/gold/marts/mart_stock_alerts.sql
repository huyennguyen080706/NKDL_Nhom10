-- Cảnh báo theo quy tắc. Grain: 1 mã / 1 ngày / 1 quy tắc.
-- Đây là tín hiệu MINH HỌA dựa trên quy tắc, không phải khuyến nghị giao dịch.
-- Các quy tắc dạng "vùng" (RSI, drawdown) chỉ phát tín hiệu tại phiên VỪA cắt ngưỡng để tránh lặp.
{% set rsi_ob = var('rsi_overbought') %}
{% set rsi_os = var('rsi_oversold') %}
{% set vol_ratio = var('volume_spike_ratio') %}
{% set move = var('large_move_pct') %}
{% set dd = var('drawdown_alert_pct') %}
with t as (

    select
        *,
        lag(sma20) over (partition by symbol order by trade_date)    as prev_sma20,
        lag(sma50) over (partition by symbol order by trade_date)    as prev_sma50,
        lag(rsi14) over (partition by symbol order by trade_date)    as prev_rsi14,
        lag(drawdown) over (partition by symbol order by trade_date) as prev_drawdown
    from {{ ref('mart_technical_indicators') }}

),

alerts as (

    select symbol, trade_date, ticker_key, date_key, close,
           'GOLDEN_CROSS' as rule_code, 'bullish' as signal,
           sma20 / sma50 - 1 as observed_value, cast(0 as {{ type_double() }}) as threshold_value,
           'SMA20 (' || {{ num_text('sma20') }} || ') cắt lên trên SMA50 (' || {{ num_text('sma50') }} || ')' as reason
    from t
    where sma20 > sma50 and prev_sma20 <= prev_sma50

    union all
    select symbol, trade_date, ticker_key, date_key, close,
           'DEATH_CROSS', 'bearish', sma20 / sma50 - 1, cast(0 as {{ type_double() }}),
           'SMA20 (' || {{ num_text('sma20') }} || ') cắt xuống dưới SMA50 (' || {{ num_text('sma50') }} || ')'
    from t
    where sma20 < sma50 and prev_sma20 >= prev_sma50

    union all
    select symbol, trade_date, ticker_key, date_key, close,
           'RSI_OVERBOUGHT', 'bearish', rsi14, cast({{ rsi_ob }} as {{ type_double() }}),
           'RSI14 = ' || {{ num_text('rsi14', 1) }} || ' vượt lên ngưỡng quá mua {{ rsi_ob }}'
    from t
    where rsi14 >= {{ rsi_ob }} and prev_rsi14 < {{ rsi_ob }}

    union all
    select symbol, trade_date, ticker_key, date_key, close,
           'RSI_OVERSOLD', 'bullish', rsi14, cast({{ rsi_os }} as {{ type_double() }}),
           'RSI14 = ' || {{ num_text('rsi14', 1) }} || ' rơi xuống ngưỡng quá bán {{ rsi_os }}'
    from t
    where rsi14 <= {{ rsi_os }} and prev_rsi14 > {{ rsi_os }}

    union all
    select symbol, trade_date, ticker_key, date_key, close,
           'VOLUME_SPIKE', 'neutral', volume_ratio_20d, cast({{ vol_ratio }} as {{ type_double() }}),
           'Khối lượng gấp ' || {{ num_text('volume_ratio_20d') }} || ' lần trung bình 20 phiên trước (ngưỡng {{ vol_ratio }})'
    from t
    where volume_ratio_20d >= {{ vol_ratio }}

    union all
    select symbol, trade_date, ticker_key, date_key, close,
           'LARGE_MOVE_UP', 'bullish', daily_return, cast({{ move }} as {{ type_double() }}),
           'Giá đóng cửa tăng ' || {{ num_text('daily_return * 100') }} || '% trong phiên (ngưỡng {{ (move * 100) | round(1) }}%)'
    from t
    where daily_return >= {{ move }}

    union all
    select symbol, trade_date, ticker_key, date_key, close,
           'LARGE_MOVE_DOWN', 'bearish', daily_return, cast(-{{ move }} as {{ type_double() }}),
           'Giá đóng cửa giảm ' || {{ num_text('abs(daily_return) * 100') }} || '% trong phiên (ngưỡng {{ (move * 100) | round(1) }}%)'
    from t
    where daily_return <= -{{ move }}

    union all
    select symbol, trade_date, ticker_key, date_key, close,
           'DEEP_DRAWDOWN', 'bearish', drawdown, cast({{ dd }} as {{ type_double() }}),
           'Giá giảm ' || {{ num_text('abs(drawdown) * 100') }} || '% so với đỉnh (' || {{ num_text('running_max_close') }}
               || '), vượt ngưỡng {{ (dd * 100) | round(1) }}%'
    from t
    where drawdown <= {{ dd }} and prev_drawdown > {{ dd }}

)

select
    {{ dbt.hash("symbol || '|' || cast(trade_date as " ~ dbt.type_string() ~ ") || '|' || rule_code") }} as alert_key,
    ticker_key,
    date_key,
    symbol,
    trade_date,
    rule_code,
    signal,
    observed_value,
    threshold_value,
    reason,
    close,
    {{ dbt.current_timestamp() }}                             as generated_at
from alerts

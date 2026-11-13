-- Chỉ báo kỹ thuật theo ngày. Grain: 1 mã / 1 ngày giao dịch.
-- Mọi cửa sổ tính trên chuỗi phiên giao dịch của chính mã đó; chỉ báo để NULL khi chưa đủ số phiên.
-- RSI14 dùng trung bình đơn giản của mức tăng/giảm 14 phiên (biến thể Cutler), không phải làm mượt Wilder.
with px as (

    select
        ticker_key,
        date_key,
        symbol,
        trade_date,
        close,
        volume,
        row_number() over (partition by symbol order by trade_date)  as session_no,
        lag(close) over (partition by symbol order by trade_date)    as prev_close,
        lag(close, 5) over (partition by symbol order by trade_date) as close_5d_ago,
        lag(close, 20) over (partition by symbol order by trade_date) as close_20d_ago
    from {{ ref('fact_price_daily') }}

),

ret as (

    select
        *,
        close / prev_close - 1                                       as daily_return,
        ln(close / prev_close)                                       as log_return,
        case when close > prev_close then close - prev_close else 0 end as gain,
        case when close < prev_close then prev_close - close else 0 end as loss
    from px

),

win as (

    select
        *,
        avg(close) over (partition by symbol order by trade_date rows between 19 preceding and current row) as sma20_raw,
        avg(close) over (partition by symbol order by trade_date rows between 49 preceding and current row) as sma50_raw,
        avg(gain) over (partition by symbol order by trade_date rows between 13 preceding and current row)  as avg_gain_14,
        avg(loss) over (partition by symbol order by trade_date rows between 13 preceding and current row)  as avg_loss_14,
        stddev_samp(daily_return) over (partition by symbol order by trade_date rows between 19 preceding and current row) as vol_20_raw,
        avg(volume) over (partition by symbol order by trade_date rows between 20 preceding and 1 preceding) as avg_volume_20d_raw,
        max(close) over (partition by symbol order by trade_date rows between unbounded preceding and current row) as running_max_close
    from ret

)

select
    ticker_key,
    date_key,
    symbol,
    trade_date,
    session_no,
    close,
    volume,
    prev_close,
    daily_return,
    log_return,
    case when close_5d_ago > 0 then close / close_5d_ago - 1 end     as return_5d,
    case when close_20d_ago > 0 then close / close_20d_ago - 1 end   as return_20d,
    case when session_no >= 20 then sma20_raw end                    as sma20,
    case when session_no >= 50 then sma50_raw end                    as sma50,
    case
        when session_no < 15 then null                               -- cần 14 thay đổi giá
        when avg_loss_14 = 0 and avg_gain_14 = 0 then 50
        when avg_loss_14 = 0 then 100
        else 100 - 100 / (1 + avg_gain_14 / avg_loss_14)
    end                                                              as rsi14,
    case when session_no >= 21 then vol_20_raw end                   as volatility_20d,
    case when session_no >= 21 then vol_20_raw * sqrt(252) end       as volatility_20d_annualized,
    case when session_no >= 21 then avg_volume_20d_raw end           as avg_volume_20d,
    case when session_no >= 21 and avg_volume_20d_raw > 0
         then volume / avg_volume_20d_raw end                        as volume_ratio_20d,
    running_max_close,
    close / running_max_close - 1                                    as drawdown
from win

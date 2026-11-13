-- So sánh cổ phiếu với VN-Index. Grain: 1 mã / 1 chỉ số / 1 ngày giao dịch.
-- Chỉ tính trên khoảng ngày CHUNG (chỉ số bắt đầu muộn hơn giá cổ phiếu); mốc so sánh lũy kế
-- là phiên chung đầu tiên của từng mã.
with stock as (

    select ticker_key, date_key, symbol, trade_date, close, daily_return
    from {{ ref('mart_technical_indicators') }}

),

idx as (

    select
        index_code,
        trade_date,
        close                                                        as index_close,
        close / lag(close) over (partition by index_code order by trade_date) - 1 as index_return
    from {{ ref('fact_index_daily') }}

),

joined as (

    select
        s.ticker_key,
        s.date_key,
        s.symbol,
        i.index_code,
        s.trade_date,
        s.close                                                      as stock_close,
        i.index_close,
        s.daily_return                                               as stock_return,
        i.index_return,
        first_value(s.close) over (partition by s.symbol, i.index_code order by s.trade_date
                                   rows between unbounded preceding and unbounded following) as stock_base_close,
        first_value(i.index_close) over (partition by s.symbol, i.index_code order by s.trade_date
                                   rows between unbounded preceding and unbounded following) as index_base_close,
        min(s.trade_date) over (partition by s.symbol, i.index_code) as common_start_date,
        row_number() over (partition by s.symbol, i.index_code order by s.trade_date) as common_session_no,
        lag(s.close, 20) over (partition by s.symbol, i.index_code order by s.trade_date) as stock_close_20d_ago,
        lag(i.index_close, 20) over (partition by s.symbol, i.index_code order by s.trade_date) as index_close_20d_ago
    from stock s
    inner join idx i on i.trade_date = s.trade_date

),

calc as (

    select
        *,
        covar_samp(stock_return, index_return) over (partition by symbol, index_code order by trade_date
                                                     rows between 59 preceding and current row) as covar_60,
        var_samp(index_return) over (partition by symbol, index_code order by trade_date
                                     rows between 59 preceding and current row)                as index_var_60
    from joined

)

select
    ticker_key,
    date_key,
    symbol,
    index_code,
    trade_date,
    common_start_date,
    stock_close,
    index_close,
    stock_return,
    index_return,
    stock_return - index_return                                      as excess_return,
    stock_close / stock_base_close - 1                               as stock_cum_return,
    index_close / index_base_close - 1                               as index_cum_return,
    (stock_close / stock_base_close) - (index_close / index_base_close) as excess_cum_return,
    (stock_close / stock_base_close) / (index_close / index_base_close) as relative_strength,
    stock_close / stock_close_20d_ago - 1                            as stock_return_20d,
    index_close / index_close_20d_ago - 1                            as index_return_20d,
    (stock_close / stock_close_20d_ago) - (index_close / index_close_20d_ago) as excess_return_20d,
    case when common_session_no >= 61 and index_var_60 > 0
         then covar_60 / index_var_60 end                            as beta_60d
from calc

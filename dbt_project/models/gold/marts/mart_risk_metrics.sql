-- Chỉ số rủi ro - lợi suất theo mã và cửa sổ phiên gần nhất. Grain: 1 mã / 1 cửa sổ (60, 120, 252 phiên).
-- Đều là PRICE return (close chưa xác minh đã điều chỉnh cổ tức), không phải total return.
-- Beta chỉ dùng các ngày giao dịch CHUNG với VN-Index; n_obs_beta cho biết số ngày chung.
-- Sharpe dùng lãi suất phi rủi ro khai báo ở var `risk_free_rate_annual`.
with ret as (

    select symbol, trade_date, close, daily_return, log_return
    from {{ ref('mart_technical_indicators') }}
    where daily_return is not null

),

ranked as (

    select *, row_number() over (partition by symbol order by trade_date desc) as rn
    from ret

),

windows as (

    select 60 as window_days union all select 120 union all select 252

),

idx as (

    select trade_date, close / lag(close) over (order by trade_date) - 1 as index_return
    from {{ ref('fact_index_daily') }}
    where index_code = 'VNINDEX'

),

win as (

    select w.window_days, r.symbol, r.trade_date, r.close, r.daily_return, r.log_return, i.index_return
    from ranked r
    inner join windows w on r.rn <= w.window_days
    left join idx i on i.trade_date = r.trade_date

),

calc as (

    select
        *,
        max(close) over (partition by symbol, window_days order by trade_date
                         rows between unbounded preceding and current row)  as run_max,
        {{ quantile_over('daily_return', 0.05, 'symbol, window_days') }}    as q05
    from win

),

agg as (

    select
        symbol,
        window_days,
        max(trade_date)                                                     as as_of_date,
        min(trade_date)                                                     as window_start_date,
        count(*)                                                            as n_obs,
        power(exp(sum(log_return)), 252.0 / count(*)) - 1                   as annualized_return,
        stddev_samp(daily_return) * sqrt(252)                               as annualized_volatility,
        min(close / run_max - 1)                                            as max_drawdown,
        -max(q05)                                                           as var95_daily,
        count(index_return)                                                 as n_obs_beta,
        covar_samp(daily_return, index_return)                              as covar_idx,
        var_samp(index_return)                                              as var_idx
    from calc
    group by symbol, window_days

)

select
    symbol,
    window_days,
    as_of_date,
    window_start_date,
    n_obs,
    n_obs = window_days                                                     as is_full_window,
    annualized_return,
    annualized_volatility,
    max_drawdown,
    var95_daily,
    case when n_obs_beta >= 30 and var_idx > 0 then covar_idx / var_idx end as beta,
    n_obs_beta,
    {{ var('risk_free_rate_annual') }}                                      as risk_free_rate_annual,
    case when annualized_volatility > 1e-12
         then (annualized_return - {{ var('risk_free_rate_annual') }}) / annualized_volatility end as sharpe
from agg

-- Tương quan Pearson của lợi suất ngày giữa từng cặp mã. Grain: 1 cặp (symbol_a < symbol_b) / 1 cửa sổ.
-- Cửa sổ = N ngày giao dịch gần nhất của thị trường (60, 120, 252); chỉ tính trên NGÀY CHUNG của hai mã.
-- quality_flag: OK khi n_obs >= 60, LOW_OBS khi ít hơn (mã niêm yết ngắn hoặc nghỉ nhiều phiên).
with ret as (

    select symbol, trade_date, daily_return
    from {{ ref('mart_technical_indicators') }}
    where daily_return is not null

),

cal as (

    select trade_date, row_number() over (order by trade_date desc) as rn
    from (select distinct trade_date from ret) d

),

windows as (

    select 60 as window_days union all select 120 union all select 252

),

win as (

    select w.window_days, r.symbol, r.trade_date, r.daily_return
    from ret r
    inner join cal c on c.trade_date = r.trade_date
    inner join windows w on c.rn <= w.window_days

)

select
    a.symbol                                                             as symbol_a,
    b.symbol                                                             as symbol_b,
    a.window_days,
    max(a.trade_date)                                                    as as_of_date,
    min(a.trade_date)                                                    as window_start_date,
    count(*)                                                             as n_obs,
    corr(a.daily_return, b.daily_return)                                 as correlation,
    case when count(*) >= 60 then 'OK' else 'LOW_OBS' end                as quality_flag
from win a
inner join win b
    on a.window_days = b.window_days and a.trade_date = b.trade_date and a.symbol < b.symbol
group by a.symbol, b.symbol, a.window_days

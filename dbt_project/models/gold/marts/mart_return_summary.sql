-- Lợi suất giá theo kỳ. Grain: 1 mã / 1 kỳ. period_type: MONTH | TRAIL_20D | TRAIL_60D | TRAIL_252D | YTD | ALL.
-- PRICE return trên close (chưa xác minh điều chỉnh cổ tức/chia tách). CAGR chỉ có khi kỳ dài từ 1 năm trở lên.
-- Tháng đầu tiên của mỗi mã không có lợi suất tháng (không có đáy kỳ trước).
with px as (

    select
        symbol, trade_date, close,
        row_number() over (partition by symbol order by trade_date desc) as rn_desc,
        row_number() over (partition by symbol order by trade_date)      as rn_asc
    from {{ ref('fact_price_daily') }}

),

monthly as (

    select
        symbol,
        extract(year from trade_date) * 100 + extract(month from trade_date) as ym,
        max(trade_date)                                                  as month_end_date,
        count(*)                                                         as n_sessions
    from px
    group by symbol, extract(year from trade_date) * 100 + extract(month from trade_date)

),

month_close as (

    select m.symbol, m.ym, m.month_end_date, m.n_sessions, p.close as end_close
    from monthly m
    inner join px p on p.symbol = m.symbol and p.trade_date = m.month_end_date

),

month_ret as (

    select
        symbol,
        'MONTH'                                                          as period_type,
        cast(ym as {{ dbt.type_string() }})                              as period_label,
        lag(month_end_date) over (partition by symbol order by ym)       as start_date,
        month_end_date                                                   as end_date,
        lag(end_close) over (partition by symbol order by ym)            as start_close,
        end_close,
        n_sessions
    from month_close

),

last_px as (

    select symbol, trade_date as end_date, close as end_close, rn_asc
    from px where rn_desc = 1

),

trail as (

    select
        l.symbol, t.period_type, t.period_type as period_label,
        s.trade_date as start_date, l.end_date, s.close as start_close, l.end_close,
        t.n as n_sessions
    from last_px l
    inner join (
        select 'TRAIL_20D' as period_type, 20 as n union all
        select 'TRAIL_60D', 60 union all select 'TRAIL_252D', 252
    ) t on l.rn_asc > t.n
    inner join px s on s.symbol = l.symbol and s.rn_desc = t.n + 1

),

year_end as (

    select symbol, extract(year from trade_date) as yr, max(trade_date) as year_end_date
    from px
    group by symbol, extract(year from trade_date)

),

ytd as (

    select
        l.symbol, 'YTD' as period_type, cast(extract(year from l.end_date) as {{ dbt.type_string() }}) as period_label,
        s.trade_date as start_date, l.end_date, s.close as start_close, l.end_close,
        l.rn_asc as n_sessions
    from last_px l
    inner join year_end y on y.symbol = l.symbol and y.yr = extract(year from l.end_date) - 1
    inner join px s on s.symbol = l.symbol and s.trade_date = y.year_end_date

),

all_ret as (

    select
        l.symbol, 'ALL' as period_type, 'ALL' as period_label,
        s.trade_date as start_date, l.end_date, s.close as start_close, l.end_close,
        l.rn_asc as n_sessions
    from last_px l
    inner join px s on s.symbol = l.symbol and s.rn_asc = 1

),

unioned as (

    select * from month_ret where start_close is not null
    union all select * from trail
    union all select * from ytd
    union all select * from all_ret

)

select
    symbol,
    period_type,
    period_label,
    start_date,
    end_date,
    n_sessions,
    start_close,
    end_close,
    end_close / start_close - 1                                          as price_return,
    {{ dbt.datediff('start_date', 'end_date', 'day') }} / 365.25         as years,
    case when {{ dbt.datediff('start_date', 'end_date', 'day') }} >= 365
         then power(end_close / start_close, 365.25 / {{ dbt.datediff('start_date', 'end_date', 'day') }}) - 1
    end                                                                  as cagr
from unioned
where start_close > 0

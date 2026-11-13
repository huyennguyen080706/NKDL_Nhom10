-- Dimension ngày. Grain: 1 dòng / ngày lịch, phủ trọn các năm có dữ liệu giá hoặc BCTC.
with all_dates as (

    select trade_date as d from {{ ref('stg_price_daily') }}
    union all
    select trade_date from {{ ref('stg_index_daily') }}
    union all
    select period_end_date from {{ ref('stg_income_statement') }}
    union all
    select period_end_date from {{ ref('stg_balance_sheet') }}
    union all
    select period_end_date from {{ ref('stg_cash_flow') }}

),

bounds as (

    select
        {{ make_date('cast(extract(year from min(d)) as ' ~ dbt.type_int() ~ ')', 1, 1) }}   as start_date,
        {{ make_date('cast(extract(year from max(d)) as ' ~ dbt.type_int() ~ ')', 12, 31) }} as end_date
    from all_dates
    where d is not null

),

spine as (

    {{ date_spine_from('bounds') }}

),

trading_days as (

    select distinct trade_date from {{ ref('stg_price_daily') }}
    union
    select distinct trade_date from {{ ref('stg_index_daily') }}

),

base as (

    select
        s.full_date,
        cast(extract(year from s.full_date) as {{ dbt.type_int() }})    as year,
        cast(extract(quarter from s.full_date) as {{ dbt.type_int() }}) as quarter,
        cast(extract(month from s.full_date) as {{ dbt.type_int() }})   as month,
        cast(extract(day from s.full_date) as {{ dbt.type_int() }})     as day_of_month,
        {{ iso_day_of_week('s.full_date') }}                            as day_of_week,
        (t.trade_date is not null)                                      as is_trading_day
    from spine s
    left join trading_days t on t.trade_date = s.full_date

)

select
    {{ date_key('full_date') }}                               as date_key,
    full_date,
    year,
    quarter,
    month,
    day_of_month,
    day_of_week,
    case day_of_week
        when 1 then 'Thứ Hai' when 2 then 'Thứ Ba' when 3 then 'Thứ Tư' when 4 then 'Thứ Năm'
        when 5 then 'Thứ Sáu' when 6 then 'Thứ Bảy' else 'Chủ Nhật'
    end                                                       as day_name,
    (day_of_week >= 6)                                        as is_weekend,
    cast(year as {{ dbt.type_string() }}) || '-Q' || cast(quarter as {{ dbt.type_string() }}) as year_quarter,
    cast(year as {{ dbt.type_string() }}) || '-'
        || case when month < 10 then '0' else '' end || cast(month as {{ dbt.type_string() }}) as year_month,
    is_trading_day
from base

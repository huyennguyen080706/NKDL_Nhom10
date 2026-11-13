-- Dimension mã chứng khoán. Grain: 1 dòng / mã (trạng thái hiện tại - SCD Type 1).
-- Lấy hợp các mã xuất hiện ở giá, hồ sơ và BCTC để fact không bị mồ côi.
with symbols as (

    select symbol from {{ ref('stg_price_daily') }}
    union
    select symbol from {{ ref('stg_company') }}
    union
    select symbol from {{ ref('stg_income_statement') }}
    union
    select symbol from {{ ref('stg_balance_sheet') }}
    union
    select symbol from {{ ref('stg_cash_flow') }}

),

price_stats as (

    select
        symbol,
        min(trade_date) as first_trade_date,
        max(trade_date) as last_trade_date,
        count(*)        as trading_days
    from {{ ref('stg_price_daily') }}
    group by symbol

),

-- Mẫu báo cáo suy ra từ bộ chỉ tiêu nguồn trả về (nguồn không có mã ngành chuẩn).
fin_template as (

    select
        symbol,
        case
            when sum(case when metric_id = 'IS_NET_INTEREST_INCOME' then 1 else 0 end) > 0 then 'bank'
            when sum(case when metric_id = 'IS_OPERATING_RESULT' then 1 else 0 end) > 0 then 'securities'
            else 'corporate'
        end              as financial_template,
        count(distinct period) as financial_periods
    from {{ ref('stg_income_statement') }}
    group by symbol

)

select
    {{ dbt.hash('s.symbol') }}                                as ticker_key,
    s.symbol,
    c.exchange,
    c.num_employees,
    c.founded_date,
    c.listing_date,
    c.charter_capital_bn_vnd,
    c.website,
    c.address,
    c.phone,
    c.email,
    c.tax_id,
    c.business_profile,
    (c.symbol is not null)                                    as has_company_profile,
    (f.symbol is not null)                                    as has_financials,
    f.financial_template,
    coalesce(f.financial_periods, 0)                          as financial_periods,
    p.first_trade_date,
    p.last_trade_date,
    coalesce(p.trading_days, 0)                               as trading_days,
    c.batch_id                                                as profile_batch_id
from symbols s
left join {{ ref('stg_company') }} c on c.symbol = s.symbol
left join price_stats p on p.symbol = s.symbol
left join fin_template f on f.symbol = s.symbol

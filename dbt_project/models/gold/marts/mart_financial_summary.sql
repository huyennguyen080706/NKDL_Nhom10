-- Tóm tắt tài chính theo kỳ. Grain: 1 mã / 1 kỳ báo cáo.
-- Lưu ý từ profiling:
--   * BS_TOTAL_ASSETS luôn NULL ở nguồn -> tổng tài sản lấy từ BS_TOTAL_LIABILITIES_AND_EQUITY
--     (tổng nguồn vốn = tổng tài sản theo đẳng thức kế toán); cột total_assets_basis ghi rõ.
--   * Ngân hàng không có "doanh thu thuần": dùng tổng thu nhập hoạt động (cộng 6 khoản thu nhập thuần).
--   * NULL không quy về 0; tỷ số để NULL khi thiếu tử/mẫu số.
--   * ROE/ROA tính trên số dư CUỐI kỳ của một quý, chưa quy năm.
--   * Kỳ 2025-Q4 ở nguồn có quy mô gấp ~4 lần các quý 2026 ở MỌI mã (nghi là số cộng dồn cả năm
--     gắn nhãn Q4). Kỳ như vậy được gắn is_period_suspect = true và KHÔNG dùng để tính tăng trưởng QoQ.
{% set bank_income_items = [
    'IS_NET_INTEREST_INCOME', 'IS_NET_FEE_AND_COMMISSION_INCOME',
    'IS_NET_GAIN_LOSS_FROM_FOREIGN_CURRENCIES_AND_GOLD_TRADING',
    'IS_NET_GAIN_LOSS_FROM_TRADING_SECURITIES', 'IS_NET_GAIN_LOSS_FROM_INVESTMENT_SECURITIES',
    'IS_NET_OTHER_INCOME'
] %}
with f as (

    select * from {{ ref('fact_financial_metric') }}

),

pivoted as (

    select
        ticker_key,
        symbol,
        period,
        fiscal_year,
        fiscal_quarter,
        period_end_date,
        period_end_date_key,
        {{ pivot_metric('IS_NET_REVENUE') }}                                  as net_revenue,
        sum(case when metric_id in ('{{ bank_income_items | join("', '") }}') then value end) as bank_operating_income,
        {{ pivot_metric('IS_GROSS_PROFIT') }}                                 as gross_profit,
        {{ pivot_metric('IS_OPERATING_PROFIT') }}                             as operating_profit,
        {{ pivot_metric('IS_PROFIT_BEFORE_TAX') }}                            as profit_before_tax,
        {{ pivot_metric('IS_NET_PROFIT_AFTER_TAX') }}                         as net_profit_after_tax,
        {{ pivot_metric('IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY') }} as net_profit_parent,
        {{ pivot_metric('BS_TOTAL_ASSETS') }}                                 as total_assets_reported,
        {{ pivot_metric('BS_TOTAL_LIABILITIES_AND_EQUITY') }}                 as total_liabilities_and_equity,
        {{ pivot_metric('BS_TOTAL_LIABILITIES') }}                            as total_liabilities,
        {{ pivot_metric('BS_EQUITY') }}                                       as equity,
        {{ pivot_metric('BS_CASH_AND_PRECIOUS_METALS') }}                     as cash_and_equivalents,
        {{ pivot_metric('CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES') }}     as net_cash_from_operating,
        {{ pivot_metric('CF_NET_CASH_FLOWS_FROM_INVESTING_ACTIVITIES') }}     as net_cash_from_investing,
        {{ pivot_metric('CF_NET_CASH_FLOWS_FROM_FINANCING_ACTIVITIES') }}     as net_cash_from_financing,
        count(*)                                                      as metrics_total,
        sum(case when value is not null then 1 else 0 end)            as metrics_with_value
    from f
    group by ticker_key, symbol, period, fiscal_year, fiscal_quarter, period_end_date, period_end_date_key

),

base as (

    select
        p.*,
        t.financial_template,
        case when t.financial_template = 'bank' then p.bank_operating_income else p.net_revenue end as revenue,
        case when t.financial_template = 'bank' then 'total_operating_income' else 'net_revenue' end as revenue_basis,
        coalesce(p.total_assets_reported, p.total_liabilities_and_equity) as total_assets,
        case
            when p.total_assets_reported is not null then 'BS_TOTAL_ASSETS'
            when p.total_liabilities_and_equity is not null then 'BS_TOTAL_LIABILITIES_AND_EQUITY'
        end                                                           as total_assets_basis
    from pivoted p
    inner join {{ ref('dim_ticker') }} t on t.ticker_key = p.ticker_key

),

flagged as (

    select
        *,
        {{ median_over('equity', 'symbol') }} as median_equity
    from base

),

checked as (

    select
        *,
        case when total_liabilities_and_equity > 0
             then (total_liabilities + equity) / total_liabilities_and_equity end as balance_identity_ratio,
        case when median_equity > 0 then equity / median_equity end           as equity_scale_ratio
    from flagged

),

suspect as (

    select
        *,
        coalesce(abs(balance_identity_ratio - 1) > {{ var('balance_identity_tolerance') }}, false)
            or coalesce(equity_scale_ratio > {{ var('period_scale_ratio_max') }}
                        or equity_scale_ratio < 1.0 / {{ var('period_scale_ratio_max') }}, false) as is_period_suspect
    from checked

),

with_prev as (

    select
        *,
        lag(is_period_suspect) over (partition by symbol order by period_end_date)    as prev_is_period_suspect,
        lag(revenue) over (partition by symbol order by period_end_date)              as prev_revenue,
        lag(net_profit_after_tax) over (partition by symbol order by period_end_date) as prev_net_profit_after_tax,
        lag(period) over (partition by symbol order by period_end_date)               as prev_period
    from suspect

)

select
    ticker_key,
    period_end_date_key,
    symbol,
    financial_template,
    period,
    fiscal_year,
    fiscal_quarter,
    period_end_date,
    'VND'                                                             as unit,
    revenue,
    revenue_basis,
    gross_profit,
    operating_profit,
    profit_before_tax,
    net_profit_after_tax,
    net_profit_parent,
    total_assets,
    total_assets_basis,
    total_liabilities,
    equity,
    cash_and_equivalents,
    net_cash_from_operating,
    net_cash_from_investing,
    net_cash_from_financing,
    case when revenue > 0 then gross_profit / revenue end             as gross_margin,
    case when revenue > 0 then net_profit_after_tax / revenue end     as net_margin,
    case when equity > 0 then total_liabilities / equity end          as debt_to_equity,
    case when total_assets > 0 then total_liabilities / total_assets end as liabilities_to_assets,
    case when equity > 0 then net_profit_after_tax / equity end       as roe_quarter,
    case when total_assets > 0 then net_profit_after_tax / total_assets end as roa_quarter,
    prev_period,
    case when prev_revenue > 0 and not is_period_suspect and not prev_is_period_suspect
         then revenue / prev_revenue - 1 end                          as revenue_growth_qoq,
    case when prev_net_profit_after_tax > 0 and not is_period_suspect and not prev_is_period_suspect
         then net_profit_after_tax / prev_net_profit_after_tax - 1 end as net_profit_growth_qoq,
    balance_identity_ratio,
    equity_scale_ratio,
    is_period_suspect,
    metrics_total,
    metrics_with_value
from with_prev

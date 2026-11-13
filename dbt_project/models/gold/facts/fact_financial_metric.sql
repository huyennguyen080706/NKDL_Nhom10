-- Fact chỉ tiêu tài chính. Grain: 1 mã / 1 kỳ / 1 loại báo cáo / 1 chỉ tiêu.
-- Nguồn không có ngày công bố (published_at): period_end_date là ngày KẾT THÚC kỳ, không phải
-- ngày thông tin có sẵn -> không dùng trực tiếp để backtest với giá (tránh look-ahead bias).
with fin as (

    select * from {{ ref('stg_income_statement') }}
    union all
    select * from {{ ref('stg_balance_sheet') }}
    union all
    select * from {{ ref('stg_cash_flow') }}

)

select
    {{ dbt.hash("f.symbol || '|' || f.period || '|' || f.report_type || '|' || f.metric_id") }} as financial_metric_key,
    t.ticker_key,
    {{ date_key('f.period_end_date') }}                       as period_end_date_key,
    f.symbol,
    f.period,
    f.period_type,
    f.fiscal_year,
    f.fiscal_quarter,
    f.period_end_date,
    f.report_type,
    f.metric_id,
    f.metric_name,
    f.metric_order,
    f.is_off_balance,
    f.unit,
    f.value,
    f.batch_id
from fin f
inner join {{ ref('dim_ticker') }} t on t.symbol = f.symbol

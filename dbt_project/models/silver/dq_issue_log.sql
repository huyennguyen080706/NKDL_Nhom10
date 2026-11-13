-- Bảng theo dõi sai lệch dữ liệu: bản ghi nghi vấn được GHI NHẬN để phân tích, không bị xóa.
-- severity: error = vi phạm quy tắc cứng | warn = cần xem xét | info = ghi nhận.
with price as (

    select * from {{ ref('stg_price_daily') }}

),

idx as (

    select * from {{ ref('stg_index_daily') }}

),

price_ret as (

    select
        p.symbol,
        p.trade_date,
        p.close,
        lag(p.close) over (partition by p.symbol order by p.trade_date) as prev_close,
        c.exchange
    from price p
    left join {{ ref('stg_company') }} c on c.symbol = p.symbol

),

-- Lịch thị trường suy ra từ dữ liệu: ngày có ít nhất một nửa số mã giao dịch.
market_calendar as (

    select trade_date
    from price
    group by trade_date
    having count(*) * 2 >= (select count(distinct symbol) from price)

),

symbol_range as (

    select symbol, min(trade_date) as first_date, max(trade_date) as last_date
    from price
    group by symbol

),

fin as (

    select * from {{ ref('stg_income_statement') }}
    union all
    select * from {{ ref('stg_balance_sheet') }}
    union all
    select * from {{ ref('stg_cash_flow') }}

),

-- Kiểm tra chéo cân đối kế toán theo từng mã / kỳ.
balance_check as (

    select
        symbol, period, period_end_date, equity, total_liabilities, total_liabilities_and_equity,
        {{ median_over('equity', 'symbol') }} as median_equity
    from (
        select
            symbol, period, period_end_date,
            {{ pivot_metric('BS_EQUITY') }}                       as equity,
            {{ pivot_metric('BS_TOTAL_LIABILITIES') }}            as total_liabilities,
            {{ pivot_metric('BS_TOTAL_LIABILITIES_AND_EQUITY') }} as total_liabilities_and_equity
        from {{ ref('stg_balance_sheet') }}
        group by symbol, period, period_end_date
    ) b

),

issues as (

    select 'OHLC_INCONSISTENT' as rule_code, 'warn' as severity, 'price_daily_raw' as source_table,
           'stg_price_daily' as silver_model, symbol, trade_date as business_date,
           cast(null as {{ dbt.type_string() }}) as business_key,
           close as observed_value,
           'high/low không bao trùm open/close' as detail
    from price where not is_ohlc_consistent

    union all
    select 'NON_POSITIVE_PRICE', 'error', 'price_daily_raw', 'stg_price_daily', symbol, trade_date,
           cast(null as {{ dbt.type_string() }}), close, 'giá OHLC <= 0 hoặc NULL'
    from price where not is_price_positive

    union all
    select 'NEGATIVE_VOLUME', 'error', 'price_daily_raw', 'stg_price_daily', symbol, trade_date,
           cast(null as {{ dbt.type_string() }}), cast(volume as {{ type_double() }}), 'khối lượng âm hoặc NULL'
    from price where not is_volume_valid

    union all
    select 'ZERO_VOLUME', 'warn', 'price_daily_raw', 'stg_price_daily', symbol, trade_date,
           cast(null as {{ dbt.type_string() }}), cast(volume as {{ type_double() }}), 'phiên không có khối lượng khớp'
    from price where volume = 0

    union all
    select 'MULTIPLE_VERSIONS', 'info', 'price_daily_raw', 'stg_price_daily', symbol, trade_date,
           cast(null as {{ dbt.type_string() }}), cast(version_count as {{ type_double() }}),
           'khóa xuất hiện ở nhiều batch; Silver giữ bản trích xuất mới nhất'
    from price where version_count > 1

    union all
    select 'RETURN_EXCEEDS_PRICE_LIMIT', 'info', 'price_daily_raw', 'stg_price_daily', symbol, trade_date,
           cast(null as {{ dbt.type_string() }}), close / prev_close - 1,
           'biến động ngày vượt biên độ sàn - có thể do giá điều chỉnh hoặc phiên đặc biệt'
    from price_ret
    where prev_close > 0
      and abs(close / prev_close - 1) > case when exchange = 'HOSE' or exchange is null
                                             then {{ var('price_limit_hose') }}
                                             else {{ var('price_limit_other') }} end

    union all
    select 'MISSING_TRADING_DAY', 'warn', 'price_daily_raw', 'stg_price_daily', r.symbol, m.trade_date,
           cast(null as {{ dbt.type_string() }}), cast(null as {{ type_double() }}),
           'thị trường có giao dịch nhưng mã không có bản ghi giá'
    from symbol_range r
    inner join market_calendar m on m.trade_date between r.first_date and r.last_date
    left join price p on p.symbol = r.symbol and p.trade_date = m.trade_date
    where p.symbol is null

    union all
    select 'OHLC_INCONSISTENT', 'warn', 'index_daily_raw', 'stg_index_daily', index_code, trade_date,
           cast(null as {{ dbt.type_string() }}), close, 'high/low không bao trùm open/close'
    from idx where not is_ohlc_consistent

    union all
    select 'NON_POSITIVE_PRICE', 'error', 'index_daily_raw', 'stg_index_daily', index_code, trade_date,
           cast(null as {{ dbt.type_string() }}), close, 'giá trị chỉ số <= 0 hoặc NULL'
    from idx where not is_price_positive

    union all
    select 'INVALID_PERIOD', 'error', report_type || '_raw', 'stg_' || report_type, symbol,
           cast(null as date), period || '|' || metric_id, cast(null as {{ type_double() }}),
           'kỳ báo cáo không đúng định dạng YYYY-Qn'
    from fin where fiscal_year is null or fiscal_quarter is null

    union all
    select 'CORE_METRIC_MISSING', 'warn', report_type || '_raw', 'stg_' || report_type, symbol,
           period_end_date, period || '|' || metric_id, cast(null as {{ type_double() }}),
           'chỉ tiêu cốt lõi NULL ở nguồn (không quy về 0)'
    from fin
    where value is null
      and metric_id in (
          'IS_NET_PROFIT_AFTER_TAX', 'BS_TOTAL_ASSETS', 'BS_TOTAL_LIABILITIES', 'BS_EQUITY',
          'BS_TOTAL_LIABILITIES_AND_EQUITY', 'CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES'
      )

    union all
    select 'BALANCE_IDENTITY_VIOLATED', 'warn', 'balance_sheet_raw', 'stg_balance_sheet', symbol,
           period_end_date, period, (total_liabilities + equity) / total_liabilities_and_equity,
           'Nợ phải trả + Vốn chủ sở hữu khác Tổng nguồn vốn quá ngưỡng {{ var('balance_identity_tolerance') }}'
    from balance_check
    where total_liabilities_and_equity > 0
      and abs((total_liabilities + equity) / total_liabilities_and_equity - 1) > {{ var('balance_identity_tolerance') }}

    union all
    select 'PERIOD_SCALE_ANOMALY', 'warn', 'balance_sheet_raw', 'stg_balance_sheet', symbol,
           period_end_date, period || '|scale', equity / median_equity,
           'Vốn chủ sở hữu của kỳ lệch hơn {{ var('period_scale_ratio_max') }} lần so với trung vị các kỳ của mã - nghi số cộng dồn nhiều kỳ'
    from balance_check
    where median_equity > 0
      and (equity / median_equity > {{ var('period_scale_ratio_max') }}
           or equity / median_equity < 1.0 / {{ var('period_scale_ratio_max') }})

    union all
    select 'UNEXPECTED_UNIT', 'warn', report_type || '_raw', 'stg_' || report_type, symbol,
           period_end_date, period || '|' || metric_id, cast(null as {{ type_double() }}),
           'đơn vị khác VND: ' || coalesce(unit, 'NULL')
    from fin where unit is null or unit <> 'VND'

)

select
    {{ dbt.hash("rule_code || '|' || source_table || '|' || symbol || '|' || coalesce(cast(business_date as " ~ dbt.type_string() ~ "), '') || '|' || coalesce(business_key, '')") }} as issue_key,
    rule_code,
    severity,
    source_table,
    silver_model,
    symbol,
    business_date,
    business_key,
    observed_value,
    detail
from issues

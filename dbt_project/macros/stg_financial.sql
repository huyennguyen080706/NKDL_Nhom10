{# Chuẩn hóa một bảng báo cáo tài chính dạng long (1 mã / 1 kỳ / 1 chỉ tiêu).
   - Giữ mã và tên chỉ tiêu của nguồn; NULL giữ nguyên, không quy về 0.
   - Khi một khóa nghiệp vụ có nhiều phiên bản (nhiều batch), chọn bản trích xuất mới nhất. #}
{% macro stg_financial(source_table, report_type, has_off_balance=false) %}
with src as (

    select
        upper(trim(symbol))                                   as symbol,
        cast(period as {{ dbt.type_string() }})               as period,
        cast(report_period as {{ dbt.type_string() }})        as period_type,
        cast(id as {{ dbt.type_string() }})                   as metric_id,
        trim(cast(name as {{ dbt.type_string() }}))           as metric_name,
        cast({{ adapter.quote('order') }} as {{ dbt.type_int() }}) as metric_order,
        cast(level as {{ dbt.type_int() }})                   as metric_level,
        {% if has_off_balance -%}
        coalesce(off_balance, false)                          as is_off_balance,
        {%- else -%}
        false                                                 as is_off_balance,
        {%- endif %}
        cast(unit as {{ dbt.type_string() }})                 as unit_raw,
        cast(value as {{ type_double() }})                    as value,
        _source                                               as source,
        _batch_id                                             as batch_id,
        _source_file                                          as source_file,
        _extracted_at                                         as extracted_at,
        _ingested_at                                          as ingested_at
    from {{ source('bronze', source_table) }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by symbol, period, metric_id
            order by extracted_at desc, ingested_at desc
        ) as rn
    from src

),

parsed as (

    select
        *,
        case when period like '____-Q_' then cast(substr(period, 1, 4) as {{ dbt.type_int() }}) end as fiscal_year,
        case when period like '____-Q_' then cast(substr(period, 7, 1) as {{ dbt.type_int() }}) end as fiscal_quarter
    from ranked
    where rn = 1

)

select
    symbol,
    '{{ report_type }}'                                       as report_type,
    period,
    period_type,
    fiscal_year,
    fiscal_quarter,
    case
        when fiscal_quarter between 1 and 4 then
            {{ make_date('fiscal_year', 'fiscal_quarter * 3', 'case when fiscal_quarter in (1, 4) then 31 else 30 end') }}
    end                                                       as period_end_date,
    metric_id,
    metric_name,
    metric_order,
    metric_level,
    is_off_balance,
    case when unit_raw in ('VNĐ', 'VND', 'đồng') then 'VND' else unit_raw end as unit,
    value,
    (value is null)                                           as is_value_missing,
    source,
    batch_id,
    source_file,
    extracted_at,
    ingested_at
from parsed
{% endmacro %}

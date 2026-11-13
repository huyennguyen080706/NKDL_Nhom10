-- Sức khỏe pipeline. Grain: 1 dòng / bảng Bronze (theo batch nạp mới nhất của bảng đó).
-- Gộp 3 góc nhìn: đối soát nạp (ingestion_audit), độ phủ/độ mới của Silver, số sai lệch đã ghi nhận.
with audit as (

    select * from {{ source('bronze', 'ingestion_audit') }}

),

batches as (

    select target_table, batch_id, max(ingested_at) as batch_ingested_at
    from audit
    where target_table is not null
    group by target_table, batch_id

),

latest_batch as (

    select target_table, batch_id, total_batches
    from (
        select
            *,
            row_number() over (partition by target_table order by batch_ingested_at desc, batch_id desc) as rn,
            count(*) over (partition by target_table) as total_batches
        from batches
    ) b
    where rn = 1

),

load_stats as (

    select
        a.target_table,
        a.batch_id                                                    as latest_batch_id,
        l.total_batches,
        count(*)                                                      as datasets_expected,
        sum(case when a.load_status in ('loaded', 'empty') then 1 else 0 end)     as datasets_loaded,
        sum(a.manifest_row_count)                                     as manifest_rows,
        sum(a.loaded_row_count)                                       as bronze_rows,
        sum(case when a.row_count_match then 0 else 1 end)            as datasets_row_mismatch,
        sum(case when a.checksum_ok = false then 1 else 0 end)        as datasets_checksum_failed,
        max(a.extracted_at)                                           as last_extracted_at,
        max(a.ingested_at)                                            as last_ingested_at
    from audit a
    inner join latest_batch l on l.target_table = a.target_table and l.batch_id = a.batch_id
    group by a.target_table, a.batch_id, l.total_batches

),

silver_stats as (

    select 'price_daily_raw' as target_table, 'stg_price_daily' as silver_model, count(*) as silver_rows,
           count(distinct symbol) as entities, min(trade_date) as min_business_date, max(trade_date) as max_business_date
    from {{ ref('stg_price_daily') }}
    union all
    select 'index_daily_raw', 'stg_index_daily', count(*), count(distinct index_code), min(trade_date), max(trade_date)
    from {{ ref('stg_index_daily') }}
    union all
    select 'company_overview_raw', 'stg_company', count(*), count(distinct symbol), cast(null as date), cast(null as date)
    from {{ ref('stg_company') }}
    union all
    select 'income_statement_raw', 'stg_income_statement', count(*), count(distinct symbol), min(period_end_date), max(period_end_date)
    from {{ ref('stg_income_statement') }}
    union all
    select 'balance_sheet_raw', 'stg_balance_sheet', count(*), count(distinct symbol), min(period_end_date), max(period_end_date)
    from {{ ref('stg_balance_sheet') }}
    union all
    select 'cash_flow_raw', 'stg_cash_flow', count(*), count(distinct symbol), min(period_end_date), max(period_end_date)
    from {{ ref('stg_cash_flow') }}

),

dq as (

    select
        source_table                                                  as target_table,
        sum(case when severity = 'error' then 1 else 0 end)           as dq_error_count,
        sum(case when severity = 'warn' then 1 else 0 end)            as dq_warn_count,
        sum(case when severity = 'info' then 1 else 0 end)            as dq_info_count
    from {{ ref('dq_issue_log') }}
    group by source_table

)

select
    l.target_table                                                    as bronze_table,
    s.silver_model,
    l.latest_batch_id,
    l.total_batches,
    l.datasets_expected,
    l.datasets_loaded,
    l.manifest_rows,
    l.bronze_rows,
    (l.manifest_rows = l.bronze_rows and l.datasets_row_mismatch = 0) as is_reconciled,
    l.datasets_checksum_failed,
    s.silver_rows,
    s.entities,
    s.min_business_date,
    s.max_business_date,
    l.last_extracted_at,
    l.last_ingested_at,
    -- Độ trễ dữ liệu giá/chỉ số: số ngày từ ngày giao dịch mới nhất đến lúc trích xuất (giờ Việt Nam).
    case when l.target_table in ('price_daily_raw', 'index_daily_raw')
         then {{ dbt.datediff('s.max_business_date', vn_date('l.last_extracted_at'), 'day') }} end as data_lag_days,
    coalesce(d.dq_error_count, 0)                                     as dq_error_count,
    coalesce(d.dq_warn_count, 0)                                      as dq_warn_count,
    coalesce(d.dq_info_count, 0)                                      as dq_info_count,
    case
        when l.datasets_loaded < l.datasets_expected
          or l.datasets_row_mismatch > 0
          or l.datasets_checksum_failed > 0
          or coalesce(d.dq_error_count, 0) > 0 then 'FAIL'
        when coalesce(d.dq_warn_count, 0) > 0 then 'WARN'
        else 'OK'
    end                                                               as status,
    {{ dbt.current_timestamp() }}                                     as refreshed_at
from load_stats l
left join silver_stats s on s.target_table = l.target_table
left join dq d on d.target_table = l.target_table

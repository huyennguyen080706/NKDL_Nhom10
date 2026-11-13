-- Hồ sơ doanh nghiệp hiện tại. Grain: 1 mã (snapshot mới nhất).
-- Nguồn chỉ có 1 snapshot/mã nên chưa đủ lịch sử để dựng SCD Type 2; nguồn cũng không có
-- tên công ty và mã ngành chuẩn (ICB/GICS).
with src as (

    select
        upper(trim(symbol))                                   as symbol,
        upper(trim(exchange))                                 as exchange,
        cast(num_employees as {{ dbt.type_int() }})           as num_employees,
        {{ vn_date('founded_date') }}                         as founded_date,
        {{ vn_date('listing_date') }}                         as listing_date,
        cast(charter_capital as {{ type_double() }})          as charter_capital_bn_vnd,
        nullif(trim(website), '')                             as website,
        nullif(trim(address), '')                             as address,
        nullif(trim(phone), '')                               as phone,
        nullif(trim(email), '')                               as email,
        nullif(trim(tax_id), '')                              as tax_id,
        nullif(trim({{ adapter.quote('profile') }}), '')      as business_profile,
        nullif(trim(history), '')                             as company_history,
        _source                                               as source,
        _batch_id                                             as batch_id,
        _source_file                                          as source_file,
        _extracted_at                                         as extracted_at,
        _ingested_at                                          as ingested_at
    from {{ source('bronze', 'company_overview_raw') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by symbol
            order by extracted_at desc, ingested_at desc
        ) as rn
    from src
    where symbol is not null

)

select
    symbol,
    exchange,
    num_employees,
    founded_date,
    listing_date,
    charter_capital_bn_vnd,
    website,
    address,
    phone,
    email,
    tax_id,
    business_profile,
    company_history,
    source,
    batch_id,
    source_file,
    extracted_at,
    ingested_at
from ranked
where rn = 1

{# Các macro che khác biệt cú pháp giữa DuckDB (local) và BigQuery (cloud). #}

{# Tên schema dùng đúng như khai báo (bronze/silver/gold), không ghép tiền tố target. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}

{% macro type_double() -%}
    {%- if target.type == 'bigquery' -%} float64 {%- else -%} double {%- endif -%}
{%- endmacro %}

{# Ngày theo giờ Việt Nam của một cột timestamp có múi giờ. #}
{% macro vn_date(col) -%}
    {%- if target.type == 'bigquery' -%}
        date({{ col }}, 'Asia/Ho_Chi_Minh')
    {%- else -%}
        cast(timezone('Asia/Ho_Chi_Minh', {{ col }}) as date)
    {%- endif -%}
{%- endmacro %}

{% macro make_date(y, m, d) -%}
    {%- if target.type == 'bigquery' -%}
        date({{ y }}, {{ m }}, {{ d }})
    {%- else -%}
        make_date({{ y }}, {{ m }}, {{ d }})
    {%- endif -%}
{%- endmacro %}

{# Thứ trong tuần theo ISO: 1 = Thứ Hai ... 7 = Chủ Nhật. #}
{% macro iso_day_of_week(col) -%}
    {%- if target.type == 'bigquery' -%}
        (mod(extract(dayofweek from {{ col }}) + 5, 7) + 1)
    {%- else -%}
        cast(isodow({{ col }}) as integer)
    {%- endif -%}
{%- endmacro %}

{# Sinh dãy ngày liên tục từ một CTE có 2 cột start_date, end_date. #}
{% macro date_spine_from(bounds_cte) -%}
    {%- if target.type == 'bigquery' -%}
        select full_date
        from {{ bounds_cte }}, unnest(generate_date_array(start_date, end_date)) as full_date
    {%- else -%}
        select cast(unnest(generate_series(
                   cast(start_date as timestamp), cast(end_date as timestamp), interval 1 day
               )) as date) as full_date
        from {{ bounds_cte }}
    {%- endif -%}
{%- endmacro %}

{# Khóa ngày dạng số nguyên yyyymmdd. #}
{% macro date_key(col) -%}
    cast(extract(year from {{ col }}) * 10000 + extract(month from {{ col }}) * 100 + extract(day from {{ col }}) as {{ dbt.type_int() }})
{%- endmacro %}

{# Số thập phân -> chuỗi làm tròn để ghép vào câu giải thích. #}
{% macro num_text(expr, decimals=2) -%}
    cast(round(cast({{ expr }} as numeric), {{ decimals }}) as {{ dbt.type_string() }})
{%- endmacro %}

{# Trung vị theo cửa sổ partition. #}
{% macro median_over(expr, partition_by) -%}
    {%- if target.type == 'bigquery' -%}
        percentile_cont({{ expr }}, 0.5) over (partition by {{ partition_by }})
    {%- else -%}
        median({{ expr }}) over (partition by {{ partition_by }})
    {%- endif -%}
{%- endmacro %}

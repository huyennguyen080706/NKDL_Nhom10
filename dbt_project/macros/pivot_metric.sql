{# Lấy giá trị một chỉ tiêu khi xoay bảng long -> wide (NULL nếu chỉ tiêu vắng mặt). #}
{% macro pivot_metric(metric) -%}
    max(case when metric_id = '{{ metric }}' then value end)
{%- endmacro %}

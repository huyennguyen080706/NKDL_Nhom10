{# Test khóa tổ hợp không trùng (grain của bảng). #}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n_rows
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}

{# Test biểu thức logic phải đúng trên mọi dòng (dòng vi phạm được trả về). #}
{% test expression_true(model, expression) %}
select *
from {{ model }}
where not ({{ expression }})
{% endtest %}

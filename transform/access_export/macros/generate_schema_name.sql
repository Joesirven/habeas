{% macro generate_schema_name(custom_schema_name, node) -%}
    {#- Use the custom schema verbatim (access_export / access_export_stg)
        instead of dbt's default <target>_<custom> concatenation. -#}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}

{% macro table_exists(schema_name, table_name) %}
    {% set relation_query %}
        select count(*) as table_count
        from `{{ target.database }}.{{ schema_name }}.INFORMATION_SCHEMA.TABLES`
        where table_name = '{{ table_name }}'
    {% endset %}
    {% set result = run_query(relation_query) %}
    {% if result and result.rows[0][0] > 0 %}
        {{ return(true) }}
    {% else %}
        {{ return(false) }}
    {% endif %}
{% endmacro %}


{# Parallel per-state dbt builds share one dataset. Suffix every model alias with
   var('state') so staging/int/build tables do not clobber each other mid-wave. #}
{% macro generate_alias_name(custom_alias_name=none, node=none) -%}
    {%- set suffix = '_' ~ (var('state') | lower) -%}
    {%- if custom_alias_name -%}
        {{ custom_alias_name | trim }}{{ suffix }}
    {%- else -%}
        {{ node.name }}{{ suffix }}
    {%- endif -%}
{%- endmacro %}


{% macro perform_serving_swap() %}
    {# State-scoped merge: replace only var('state') rows so other states stay intact.
       Build tables are written by mart_* as *_hash__build_<state> (see
       generate_alias_name). First create renames build → serving; later runs
       DELETE state + INSERT from that state's build only. #}
    {% if not execute or not var('perform_serving_swap', true) %}
        {{ return('') }}
    {% endif %}

    {% set schema = target.schema %}
    {% set project = target.database %}
    {% set state = var('state') %}
    {% set state_suffix = state | lower %}
    {% set serving_tables = ['email_hash', 'phone_hash', 'ndz_hash'] %}
    {% set fq = project ~ '.' ~ schema %}

    {% for name in serving_tables %}
        {% set build_name = name ~ '__build_' ~ state_suffix %}

        {% if not table_exists(schema, build_name) %}
            {{ log('Skip serving swap for ' ~ name ~ ': ' ~ build_name ~ ' not found', info=true) }}
        {% elif not table_exists(schema, name) %}
            {% do run_query(
                'alter table `' ~ fq ~ '.' ~ build_name ~ '` rename to `' ~ name ~ '`'
            ) %}
            {{ log('Serving create: ' ~ build_name ~ ' -> ' ~ name ~ ' (state=' ~ state ~ ')', info=true) }}
        {% else %}
            {% do run_query(
                'delete from `' ~ fq ~ '.' ~ name ~ '` where state = \'' ~ state ~ '\''
            ) %}
            {% do run_query(
                'insert into `' ~ fq ~ '.' ~ name ~ '` (hash_value, dwid, state, built_at)
                 select hash_value, dwid, state, built_at from `' ~ fq ~ '.' ~ build_name ~ '`
                 where state = \'' ~ state ~ '\''
            ) %}
            {% do run_query('drop table if exists `' ~ fq ~ '.' ~ build_name ~ '`') %}
            {{ log('Serving merge: ' ~ build_name ~ ' into ' ~ name ~ ' for state=' ~ state, info=true) }}
        {% endif %}
    {% endfor %}
{% endmacro %}

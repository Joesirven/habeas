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
       Durable per-state artifacts (see generate_alias_name):
         - stg_*_<state>, int_*_<state>  — hashing work for one state
         - *_hash__build_<state>         — mart build for one state
       National contract: email_hash / phone_hash / ndz_hash stay shared.
       Refresh CA = rebuild CA int/build, then patch serving WHERE state='CA'.
       Build tables are retained after merge (not renamed away or dropped) so
       parallel refreshes stay isolated and ops can inspect the last good slice. #}
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
            {# COPY keeps the durable build; rename would destroy the per-state artifact. #}
            {% do run_query(
                'create table `' ~ fq ~ '.' ~ name ~ '` copy `' ~ fq ~ '.' ~ build_name ~ '`'
            ) %}
            {{ log('Serving create: copy ' ~ build_name ~ ' -> ' ~ name ~ ' (state=' ~ state ~ '; build retained)', info=true) }}
        {% else %}
            {% do run_query(
                'delete from `' ~ fq ~ '.' ~ name ~ '` where state = \'' ~ state ~ '\''
            ) %}
            {% do run_query(
                'insert into `' ~ fq ~ '.' ~ name ~ '` (hash_value, dwid, state, built_at)
                 select hash_value, dwid, state, built_at from `' ~ fq ~ '.' ~ build_name ~ '`
                 where state = \'' ~ state ~ '\''
            ) %}
            {{ log('Serving merge: ' ~ build_name ~ ' into ' ~ name ~ ' for state=' ~ state ~ ' (build retained)', info=true) }}
        {% endif %}
    {% endfor %}
{% endmacro %}

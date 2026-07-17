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


{% macro perform_serving_swap() %}
    {% if not execute or not var('perform_serving_swap', true) %}
        {{ return('') }}
    {% endif %}
    {% if flags.WHICH not in ['run', 'build'] %}
        {{ return('') }}
    {% endif %}

    {% set schema = target.schema %}
    {% set project = target.database %}
    {% set serving_tables = ['email_hash', 'phone_hash', 'ndz_hash'] %}

    {% for name in serving_tables %}
        {% set build_name = name ~ '__build' %}
        {% set old_name = name ~ '__old' %}
        {% set fq = project ~ '.' ~ schema %}

        {% if not table_exists(schema, build_name) %}
            {{ log('Skip serving swap for ' ~ name ~ ': ' ~ build_name ~ ' not found', info=true) }}
        {% else %}
            {% do run_query('drop table if exists `' ~ fq ~ '.' ~ old_name ~ '`') %}

            {% if table_exists(schema, name) %}
                {% do run_query(
                    'alter table `' ~ fq ~ '.' ~ name ~ '` rename to `' ~ old_name ~ '`'
                ) %}
            {% endif %}

            {% do run_query(
                'alter table `' ~ fq ~ '.' ~ build_name ~ '` rename to `' ~ name ~ '`'
            ) %}
            {% do run_query('drop table if exists `' ~ fq ~ '.' ~ old_name ~ '`') %}

            {{ log('Serving swap complete: ' ~ build_name ~ ' -> ' ~ name, info=true) }}
        {% endif %}
    {% endfor %}
{% endmacro %}

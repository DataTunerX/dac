from datetime import datetime

DEFAULT_SQL_PROMPT = """
You are an expert at answering questions based on the provided postgres database schema. Your task is to provide accurate SQL queries based on the given schema information.

Requirements:
1. Generate a complete, executable postgres query that can be run directly
2. Query only necessary columns
3. Wrap column names in double quotes (") as delimited identifiers
4. Unless specified, limit results to 12 rows
5. Use date('now') for current date references
6. The response format should not include special characters like ```, \n, \", etc.
7. If there are some calculations that need to be performed, you can use functions in SQL, such as SUM, COUNT, and other methods.


Query Guidelines:
- Ensure the query matches the exact postgres syntax
- Only use columns that exist in the provided tables
- Add appropriate table joins with correct join conditions
- Include WHERE clauses to filter data as needed
- Add ORDER BY when sorting is beneficial
- Use appropriate data type casting


Common Pitfalls to Avoid:
- NULL handling in NOT IN clauses
- UNION vs UNION ALL usage
- Exclusive range conditions
- Data type mismatches
- Missing or incorrect quotes around identifiers
- Wrong function arguments
- Incorrect join conditions

"""

def build_postgres_prompt(background_knowledge, fewshots, schema_results, custom_sql_prompt=None):
    if custom_sql_prompt is None:
        custom_sql_prompt = DEFAULT_SQL_PROMPT

    schema_str = format_schema_to_markdown(schema_results) if schema_results else "No schema information available"
    
    prompt_parts = [custom_sql_prompt]
    
    if background_knowledge:
        prompt_parts.append(f"\nBackground Knowledge:\n{background_knowledge}")
    
    prompt_parts.append(f"\n\nDatabase Schema:\n{schema_str}")
    
    if fewshots:
        prompt_parts.append(f"\n\nExamples:\n{fewshots}")
    
    prompt_parts.append("""
Please provide an appropriate SQL query based on the above information.
Return your response in JSON format with the query.
""")
    
    return "\n".join(prompt_parts)


def format_schema_to_markdown(schema_results):
    if not schema_results:
        return "No schema information available"
    
    formatted = []
    for table_info in schema_results:
        table_name = table_info.get('table_name', 'unknown')
        table_comment = table_info.get('table_comment', '')
        
        formatted.append(f"\n## Table: `{table_name}`")
        if table_comment:
            formatted.append(f"*{table_comment}*")
        
        formatted.append("\n| Column | Type | Nullable | Key | Comment |")
        formatted.append("|--------|------|----------|-----|---------|")
        
        for column in table_info.get('columns', []):
            col_name = column.get('column_name', '')
            col_type = column.get('column_type', '')
            nullable = column.get('is_nullable', '')
            col_key = column.get('column_key', '')
            col_comment = column.get('column_comment', '')
            
            formatted.append(
                f"| `{col_name}` | `{col_type}` | {nullable} | {col_key} | {col_comment} |"
            )
    
    return "\n".join(formatted)

# def format_schema_to_markdown(schema_results):
#     if not schema_results:
#         return "No schema information available"
    
#     formatted = []
#     for table_info in schema_results:
#         table_name = table_info.get('table_name', 'unknown')
#         table_comment = table_info.get('table_comment', '')
        
#         formatted.append(f"\n## Table: `{table_name}`")
#         if table_comment:
#             formatted.append(f"*{table_comment}*")
        
#         formatted.append("\n| Column | Type | Nullable | Key | Comment |")
#         formatted.append("|--------|------|----------|-----|---------|")
        
#         for column in table_info.get('columns', []):
#             col_name = column.get('COLUMN_NAME', '')
#             col_type = column.get('COLUMN_TYPE', '')
#             nullable = column.get('IS_NULLABLE', '')
#             col_key = column.get('COLUMN_KEY', '')
#             col_comment = column.get('COLUMN_COMMENT', '')
            
#             formatted.append(
#                 f"| `{col_name}` | `{col_type}` | {nullable} | {col_key} | {col_comment} |"
#             )
    
#     return "\n".join(formatted)

def format_one_schema_to_markdown(table_info):
    if not table_info: 
        return "No schema information available"
    
    formatted = []
    
    table_name = table_info.get('table_name', 'unknown')
    table_comment = table_info.get('table_comment', '')
        
    formatted.append(f"\n## Table: `{table_name}`")
    if table_comment:
        formatted.append(f"*{table_comment}*")
        
    formatted.append("\n| Column | Type | Nullable | Key | Comment |")
    formatted.append("|--------|------|----------|-----|---------|")
        
    for column in table_info.get('columns', []):
        col_name = column.get('COLUMN_NAME', '')
        col_type = column.get('COLUMN_TYPE', '')
        nullable = column.get('IS_NULLABLE', '')
        col_key = column.get('COLUMN_KEY', '')
        col_comment = column.get('COLUMN_COMMENT', '')
            
        formatted.append(
            f"| `{col_name}` | `{col_type}` | {nullable} | {col_key} | {col_comment} |"
        )
    
    return "\n".join(formatted)


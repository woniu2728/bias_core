from django.db import connection


def dict_fetch_all(sql: str, params=None) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params or ())
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def dict_fetch_one(sql: str, params=None) -> dict | None:
    rows = dict_fetch_all(sql, params)
    return rows[0] if rows else None

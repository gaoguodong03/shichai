#!/usr/bin/env python3
"""Tiny SQLite demo script for validating script skills."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Any


PRESET_SQL = {
    "overview": """
        select 'customers' as metric, count(*) as value from customers
        union all
        select 'orders', count(*) from orders
        union all
        select 'line_items', count(*) from order_items
        union all
        select 'gross_amount_cents', sum(quantity * unit_price_cents) from order_items
    """,
    "customers": """
        select id, name, city
        from customers
        order by id
    """,
    "orders": """
        select
          orders.id as order_id,
          customers.name as customer,
          orders.ordered_on,
          products,
          total_cents
        from orders
        join customers on customers.id = orders.customer_id
        join (
          select
            order_id,
            group_concat(product || ' x' || quantity, ', ') as products,
            sum(quantity * unit_price_cents) as total_cents
          from order_items
          group by order_id
        ) totals on totals.order_id = orders.id
        order by orders.id
    """,
    "top_customer": """
        select
          customers.name,
          customers.city,
          sum(order_items.quantity * order_items.unit_price_cents) as total_cents
        from customers
        join orders on orders.customer_id = customers.id
        join order_items on order_items.order_id = orders.id
        group by customers.id
        order by total_cents desc
        limit 1
    """,
}


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


def build_demo_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        create table customers (
          id integer primary key,
          name text not null,
          city text not null
        );

        create table orders (
          id integer primary key,
          customer_id integer not null references customers(id),
          ordered_on text not null
        );

        create table order_items (
          id integer primary key,
          order_id integer not null references orders(id),
          product text not null,
          quantity integer not null,
          unit_price_cents integer not null
        );

        insert into customers(id, name, city) values
          (1, '北邮实验室', '北京'),
          (2, '四九书房', '杭州'),
          (3, '沙箱测试组', '深圳');

        insert into orders(id, customer_id, ordered_on) values
          (101, 1, '2026-05-01'),
          (102, 2, '2026-05-03'),
          (103, 1, '2026-05-06'),
          (104, 3, '2026-05-09');

        insert into order_items(id, order_id, product, quantity, unit_price_cents) values
          (1, 101, 'notebook', 3, 1299),
          (2, 101, 'pen', 10, 199),
          (3, 102, 'coffee', 2, 3299),
          (4, 103, 'keyboard', 1, 6999),
          (5, 104, 'mouse', 4, 2599);
        """
    )
    return conn


def validate_readonly_sql(sql: str) -> str:
    normalized = sql.strip()
    if not normalized:
        raise ValueError("empty_sql")
    lowered = normalized.lower()
    if not lowered.startswith(("select", "with", "pragma")):
        raise ValueError("only_select_with_pragma_allowed")
    return normalized


def query_rows(conn: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    cursor = conn.execute(sql)
    return [dict(row) for row in cursor.fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a read-only query against a demo SQLite database.")
    parser.add_argument("--preset", choices=sorted(PRESET_SQL), default="overview")
    parser.add_argument("--sql", help="Read-only SQL. Allowed prefixes: SELECT, WITH, PRAGMA.")
    args = parser.parse_args()

    try:
        sql = validate_readonly_sql(args.sql) if args.sql else PRESET_SQL[args.preset]
        conn = build_demo_db()
        rows = query_rows(conn, sql)
    except Exception as exc:
        emit(
            {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
            },
            exit_code=1,
        )

    emit(
        {
            "ok": True,
            "preset": None if args.sql else args.preset,
            "row_count": len(rows),
            "rows": rows,
        }
    )


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(1)

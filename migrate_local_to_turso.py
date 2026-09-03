"""Copy rows from local expense_tracker.db into Turso."""

import sqlite3
from pathlib import Path

from db import get_connection, get_or_create_category, init_db, list_transactions

LOCAL_DB = Path(__file__).parent / "expense_tracker.db"


def read_local() -> dict:
    if not LOCAL_DB.exists():
        raise FileNotFoundError(f"Local database not found: {LOCAL_DB}")

    conn = sqlite3.connect(LOCAL_DB)
    conn.row_factory = sqlite3.Row
    try:
        categories = [
            dict(row)
            for row in conn.execute(
                "SELECT id, name, created_at FROM categories ORDER BY id"
            )
        ]
        transactions = [
            dict(row)
            for row in conn.execute(
                """
                SELECT t.*, c.name AS category_name
                FROM transactions t
                LEFT JOIN categories c ON t.category_id = c.id
                ORDER BY t.id
                """
            )
        ]
    finally:
        conn.close()

    return {"categories": categories, "transactions": transactions}


def insert_remote_transaction(tx: dict, category_id: int | None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO transactions (
                chat_id, type, amount, category_id, description,
                source_text, telegram_message_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))
            """,
            (
                tx["chat_id"],
                tx["type"],
                tx["amount"],
                category_id,
                tx.get("description"),
                tx.get("source_text"),
                tx.get("telegram_message_id"),
                tx.get("created_at"),
            ),
        )


def main() -> None:
    local = read_local()
    print(
        f"Local SQLite: {len(local['categories'])} categories, "
        f"{len(local['transactions'])} transactions"
    )

    init_db()
    existing = list_transactions(limit=1000)
    if existing:
        print(f"Turso already has {len(existing)} transactions. Aborting to avoid duplicates.")
        print("Empty the Turso tables first if you want a clean import.")
        return

    for category in local["categories"]:
        get_or_create_category(category["name"])
        print(f"Category: {category['name']}")

    imported = 0
    for tx in local["transactions"]:
        category_id = None
        if tx.get("category_name"):
            category_id = get_or_create_category(tx["category_name"])
        insert_remote_transaction(tx, category_id)
        imported += 1
        print(
            f"Imported #{tx['id']} {tx['type']} {tx['amount']} "
            f"{tx.get('description') or ''}"
        )

    remote = list_transactions(limit=1000)
    print(f"Done. Imported {imported} transactions. Turso now has {len(remote)}.")


if __name__ == "__main__":
    main()

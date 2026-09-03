import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import DB_PATH

logger = logging.getLogger(__name__)

TRANSACTION_TYPES = frozenset({"expense", "income", "adjustment"})


def init_db() -> None:
    logger.info("Initializing database path=%s", DB_PATH)
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('expense', 'income', 'adjustment')),
                amount REAL NOT NULL,
                category_id INTEGER REFERENCES categories(id),
                description TEXT,
                source_text TEXT,
                telegram_message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(chat_id, telegram_message_id)
            );

            CREATE INDEX IF NOT EXISTS idx_transactions_chat_created
                ON transactions(chat_id, created_at);
            """
        )
    logger.info("Database ready")


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        logger.exception("Database transaction rolled back")
        conn.rollback()
        raise
    finally:
        conn.close()


def normalize_category(name: str) -> str:
    return name.strip().title()


def get_category_names() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT name FROM categories ORDER BY name").fetchall()
    return [row["name"] for row in rows]


def get_or_create_category(name: str) -> int:
    normalized = normalize_category(name)
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO categories (name) VALUES (?)",
            (normalized,),
        )
        row = conn.execute(
            "SELECT id FROM categories WHERE name = ?",
            (normalized,),
        ).fetchone()
    return row["id"]


def transaction_exists(chat_id: int, telegram_message_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM transactions
            WHERE chat_id = ? AND telegram_message_id = ?
            """,
            (chat_id, telegram_message_id),
        ).fetchone()
    return row is not None


def get_balance(chat_id: int) -> float:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0)
                + COALESCE(SUM(CASE WHEN type = 'adjustment' THEN amount ELSE 0 END), 0)
                - COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0)
                AS balance
            FROM transactions
            WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()
    return float(row["balance"])


def insert_transaction(
    chat_id: int,
    tx_type: str,
    amount: float,
    *,
    category_id: int | None = None,
    description: str | None = None,
    source_text: str | None = None,
    telegram_message_id: int | None = None,
) -> int:
    if tx_type not in TRANSACTION_TYPES:
        raise ValueError(f"Invalid transaction type: {tx_type}")

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO transactions (
                chat_id, type, amount, category_id, description,
                source_text, telegram_message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                tx_type,
                amount,
                category_id,
                description,
                source_text,
                telegram_message_id,
            ),
        )
        return cursor.lastrowid


def set_balance(
    chat_id: int,
    target_amount: float,
    telegram_message_id: int | None = None,
) -> float:
    current = get_balance(chat_id)
    delta = target_amount - current
    if delta == 0:
        return current

    insert_transaction(
        chat_id,
        "adjustment",
        delta,
        description="Balance sync",
        source_text=f"/balance {target_amount:g}",
        telegram_message_id=telegram_message_id,
    )
    logger.info(
        "Balance adjustment chat_id=%s current=%s target=%s delta=%s",
        chat_id,
        current,
        target_amount,
        delta,
    )
    return target_amount


def get_category_name(category_id: int | None) -> str | None:
    if category_id is None:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT name FROM categories WHERE id = ?",
            (category_id,),
        ).fetchone()
    return row["name"] if row else None


def get_summary_by_category(
    chat_id: int,
    start: datetime,
    end: datetime,
) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT c.name AS category, SUM(t.amount) AS total
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            WHERE t.chat_id = ?
              AND t.type = 'expense'
              AND t.created_at >= ?
              AND t.created_at <= ?
            GROUP BY c.name
            ORDER BY total DESC
            """,
            (chat_id, start.isoformat(), end.isoformat()),
        ).fetchall()
    return [{"category": row["category"], "total": float(row["total"])} for row in rows]


def get_expense_total(chat_id: int, start: datetime, end: datetime) -> float:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM transactions
            WHERE chat_id = ?
              AND type = 'expense'
              AND created_at >= ?
              AND created_at <= ?
            """,
            (chat_id, start.isoformat(), end.isoformat()),
        ).fetchone()
    return float(row["total"])


def get_month_aggregates(chat_id: int, year: int, month: int) -> dict:
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    from datetime import timedelta

    end = end - timedelta(microseconds=1)

    categories = get_summary_by_category(chat_id, start, end)
    expense_total = get_expense_total(chat_id, start, end)

    if month == 1:
        prev_start = datetime(year - 1, 12, 1)
        prev_end = datetime(year, 1, 1) - timedelta(microseconds=1)
    else:
        prev_start = datetime(year, month - 1, 1)
        prev_end = start - timedelta(microseconds=1)

    prev_total = get_expense_total(chat_id, prev_start, prev_end)

    return {
        "year": year,
        "month": month,
        "categories": categories,
        "expense_total": expense_total,
        "previous_month_total": prev_total,
        "balance": get_balance(chat_id),
    }


def get_last_transactions(chat_id: int, limit: int = 5) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT t.*, c.name AS category_name
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.chat_id = ?
            ORDER BY t.id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_transaction(chat_id: int, tx_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT t.*, c.name AS category_name
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.chat_id = ? AND t.id = ?
            """,
            (chat_id, tx_id),
        ).fetchone()
    return _row_to_dict(row) if row else None


def delete_transaction(chat_id: int, tx_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM transactions WHERE chat_id = ? AND id = ?",
            (chat_id, tx_id),
        )
    return cursor.rowcount > 0


def update_transaction(
    chat_id: int,
    tx_id: int,
    *,
    amount: float | None = None,
    tx_type: str | None = None,
    category_id: int | None = None,
    description: str | None = None,
) -> bool:
    tx = get_transaction(chat_id, tx_id)
    if not tx:
        return False

    fields = []
    values = []

    if amount is not None:
        fields.append("amount = ?")
        values.append(amount)
    if tx_type is not None:
        fields.append("type = ?")
        values.append(tx_type)
    if category_id is not None:
        fields.append("category_id = ?")
        values.append(category_id)
    if description is not None:
        fields.append("description = ?")
        values.append(description)

    if not fields:
        return True

    values.extend([chat_id, tx_id])
    with get_connection() as conn:
        conn.execute(
            f"UPDATE transactions SET {', '.join(fields)} WHERE chat_id = ? AND id = ?",
            values,
        )
    return True


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}

import asyncio
import logging
import re
from datetime import datetime, timedelta

from db import (
    delete_transaction,
    get_balance,
    get_category_names,
    get_expense_total,
    get_last_transactions,
    get_month_aggregates,
    get_or_create_category,
    get_summary_by_category,
    get_transaction,
    set_balance,
    update_transaction,
)
from llm import analyze_month, parse_transaction
from pipeline import format_confirmation, format_inr, process_transaction

logger = logging.getLogger(__name__)


def help_text() -> str:
    return (
        "Expense Tracker Bot\n\n"
        "Log spending:\n"
        "• Send a voice note\n"
        "• Or type: 150 biriyani\n\n"
        "Commands:\n"
        "/balance — show current balance\n"
        "/balance 45000 — sync balance to ₹45,000\n"
        "/summary — this month's expenses\n"
        "/summary today|yesterday|week|month\n"
        "/summary 1 Sep to 15 Sep — custom range\n"
        "/analyze — analyze this calendar month\n"
        "/analyze 2026-08 — analyze a specific month\n"
        "/last — show recent transactions\n"
        "/delete last — delete last transaction\n"
        "/delete 12 — delete transaction by id\n"
        "/edit last 200 biriyani — edit last transaction\n"
        "/edit 12 amount 200 — edit transaction by id"
    )


def is_command(text: str) -> bool:
    return text.startswith("/")


def parse_summary_range(args: str) -> tuple[datetime, datetime, str]:
    args = args.strip().lower()

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if not args or args == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now
        label = "this month"
    elif args == "today":
        start = today_start
        end = now
        label = "today"
    elif args == "yesterday":
        start = today_start - timedelta(days=1)
        end = today_start - timedelta(microseconds=1)
        label = "yesterday"
    elif args == "week":
        start = today_start - timedelta(days=today_start.weekday())
        end = now
        label = "this week"
    else:
        match = re.match(
            r"(\d{1,2})\s+([a-z]+)\s+to\s+(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?",
            args,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError(
                "Invalid range. Try: /summary today, /summary week, or /summary 1 Sep to 15 Sep"
            )

        day1, mon1, day2, mon2, year = match.groups()
        year = int(year) if year else now.year
        start = _parse_day_month(int(day1), mon1, year)
        end_day = _parse_day_month(int(day2), mon2, year)
        end = end_day.replace(hour=23, minute=59, second=59, microsecond=999999)
        label = f"{start.strftime('%-d %b')} to {end.strftime('%-d %b %Y')}"

    return start, end, label


def _parse_day_month(day: int, month_name: str, year: int) -> datetime:
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(f"{day} {month_name[:3].title()} {year}", fmt)
        except ValueError:
            continue
    raise ValueError(f"Could not parse date: {day} {month_name}")


def format_summary(chat_id: int, start: datetime, end: datetime, label: str) -> str:
    rows = get_summary_by_category(chat_id, start, end)
    total = get_expense_total(chat_id, start, end)

    if not rows:
        return f"No expenses for {label}."

    lines = [f"Summary ({label}):", ""]
    for row in rows:
        lines.append(f"• {row['category']}: {format_inr(row['total'])}")
    lines.append("")
    lines.append(f"Total: {format_inr(total)}")
    lines.append(f"Balance: {format_inr(get_balance(chat_id))}")
    return "\n".join(lines)


def format_last_transactions(chat_id: int) -> str:
    rows = get_last_transactions(chat_id, limit=5)
    if not rows:
        return "No transactions yet."

    lines = ["Recent transactions:", ""]
    for row in rows:
        category = row.get("category_name") or "-"
        desc = row.get("description") or "-"
        lines.append(
            f"#{row['id']} {row['type']} {format_inr(abs(row['amount']))} "
            f"{desc} ({category})"
        )
    return "\n".join(lines)


async def handle_command(text: str, chat_id: int, message_id: int) -> str:
    parts = text.strip().split(maxsplit=1)
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    logger.info("Handling command chat_id=%s command=%s", chat_id, command)

    if command in {"/start", "/help"}:
        return help_text()

    if command == "/balance":
        if not args:
            return f"Current balance: {format_inr(get_balance(chat_id))}"
        try:
            amount = float(args.replace(",", ""))
        except ValueError:
            return "Usage: /balance 45000"
        new_balance = set_balance(chat_id, amount, telegram_message_id=message_id)
        logger.info("Balance synced chat_id=%s target=%s", chat_id, amount)
        return f"Balance synced to {format_inr(new_balance)}."

    if command == "/summary":
        try:
            start, end, label = parse_summary_range(args)
        except ValueError as exc:
            return str(exc)
        return format_summary(chat_id, start, end, label)

    if command == "/analyze":
        now = datetime.now()
        if args:
            match = re.match(r"^(\d{4})-(\d{1,2})$", args.strip())
            if not match:
                return "Usage: /analyze or /analyze 2026-08"
            year, month = int(match.group(1)), int(match.group(2))
        else:
            year, month = now.year, now.month

        aggregates = get_month_aggregates(chat_id, year, month)
        result = await asyncio.to_thread(analyze_month, aggregates)
        if result.get("error"):
            return f"Failed: {result['error']}"
        return result["text"]

    if command == "/last":
        return format_last_transactions(chat_id)

    if command == "/delete":
        tx = _resolve_transaction(chat_id, args)
        if isinstance(tx, str):
            return tx
        if delete_transaction(chat_id, tx["id"]):
            logger.info("Deleted transaction chat_id=%s id=%s", chat_id, tx["id"])
            return (
                f"Deleted #{tx['id']}. "
                f"Balance: {format_inr(get_balance(chat_id))}."
            )
        return "Could not delete transaction."

    if command == "/edit":
        return await _handle_edit(chat_id, args)

    return "Unknown command. Send /help for options."


def _resolve_transaction(chat_id: int, args: str) -> dict | str:
    args = args.strip()
    if not args:
        return "Usage: /delete last or /delete 12"

    if args.lower().startswith("last"):
        rows = get_last_transactions(chat_id, limit=1)
        if not rows:
            return "No transactions to edit."
        return rows[0]

    if args.split()[0].isdigit():
        tx_id = int(args.split()[0])
        tx = get_transaction(chat_id, tx_id)
        if not tx:
            return f"Transaction #{tx_id} not found."
        return tx

    return "Usage: /delete last or /delete 12"


async def _handle_edit(chat_id: int, args: str) -> str:
    args = args.strip()
    if not args:
        return "Usage: /edit last 200 biriyani or /edit 12 amount 200"

    if args.lower().startswith("last"):
        rest = args[4:].strip()
        rows = get_last_transactions(chat_id, limit=1)
        if not rows:
            return "No transactions to edit."
        tx = rows[0]
    else:
        parts = args.split(maxsplit=1)
        if not parts[0].isdigit():
            return "Usage: /edit last 200 biriyani or /edit 12 amount 200"
        tx = get_transaction(chat_id, int(parts[0]))
        if not tx:
            return f"Transaction #{parts[0]} not found."
        rest = parts[1] if len(parts) > 1 else ""

    if not rest:
        return "Tell me what to change, e.g. /edit last 200 biriyani"

    if rest.lower().startswith("amount"):
        try:
            amount = float(rest.split(maxsplit=1)[1].replace(",", ""))
        except (IndexError, ValueError):
            return "Usage: /edit 12 amount 200"
        update_transaction(chat_id, tx["id"], amount=amount)
        balance = get_balance(chat_id)
        return f"Updated #{tx['id']} amount to {format_inr(amount)}. Balance {format_inr(balance)}."

    parsed = await asyncio.to_thread(parse_transaction, rest, get_category_names())
    if parsed.get("error"):
        return f"Failed: {parsed['error']}"

    if not parsed.get("is_transaction"):
        return "Could not parse edit text. Try: /edit last 200 biriyani"

    category_id = None
    if parsed["type"] == "expense":
        category_id = get_or_create_category(parsed["category"])

    update_transaction(
        chat_id,
        tx["id"],
        amount=parsed["amount"],
        tx_type=parsed["type"],
        category_id=category_id,
        description=parsed["description"],
    )
    balance = get_balance(chat_id)
    category_name = parsed.get("category") if parsed["type"] == "expense" else None
    return format_confirmation(
        tx["id"],
        parsed["type"],
        parsed["amount"],
        parsed["description"],
        category_name,
        balance,
    )

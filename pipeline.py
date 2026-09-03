import asyncio
import logging

import httpx

from config import TG
from db import (
    get_balance,
    get_category_names,
    get_or_create_category,
    insert_transaction,
    transaction_exists,
)
from llm import parse_transaction

logger = logging.getLogger(__name__)


def format_inr(amount: float) -> str:
    return f"₹{amount:,.0f}"


def format_confirmation(
    tx_id: int,
    tx_type: str,
    amount: float,
    description: str,
    category: str | None,
    balance: float,
) -> str:
    if tx_type == "expense":
        action = "Logged"
        detail = f"{format_inr(amount)} on {description} ({category})"
    elif tx_type == "income":
        action = "Recorded income"
        detail = f"{format_inr(amount)} — {description}"
    else:
        action = "Recorded"
        detail = f"{format_inr(amount)} — {description}"

    return f"{action} {detail}. Id {tx_id}. Balance {format_inr(balance)}."


async def process_transaction(text: str, chat_id: int, message_id: int) -> str:
    logger.info(
        "Processing transaction chat_id=%s message_id=%s text=%r",
        chat_id,
        message_id,
        text,
    )

    if transaction_exists(chat_id, message_id):
        logger.warning(
            "Duplicate transaction skipped chat_id=%s message_id=%s",
            chat_id,
            message_id,
        )
        return "Already logged."

    categories = get_category_names()
    parsed = await asyncio.to_thread(parse_transaction, text, categories)

    if parsed.get("error"):
        logger.error(
            "Transaction parse failed chat_id=%s message_id=%s error=%s",
            chat_id,
            message_id,
            parsed["error"],
        )
        return f"Failed: {parsed['error']}\nSource: {text}"

    if not parsed.get("is_transaction"):
        logger.warning(
            "Message is not a transaction chat_id=%s message_id=%s text=%r",
            chat_id,
            message_id,
            text,
        )
        return f"That doesn't look like an expense or income.\nSource: {text}"

    category_id = None
    if parsed["type"] == "expense":
        category_id = get_or_create_category(parsed["category"])

    tx_id = insert_transaction(
        chat_id,
        parsed["type"],
        parsed["amount"],
        category_id=category_id,
        description=parsed["description"],
        source_text=text,
        telegram_message_id=message_id,
    )

    balance = get_balance(chat_id)
    category_name = parsed.get("category") if parsed["type"] == "expense" else None
    logger.info(
        "Transaction saved id=%s chat_id=%s type=%s amount=%s balance=%s",
        tx_id,
        chat_id,
        parsed["type"],
        parsed["amount"],
        balance,
    )
    return format_confirmation(
        tx_id,
        parsed["type"],
        parsed["amount"],
        parsed["description"],
        category_name,
        balance,
    )


async def send_telegram_message(chat_id: int, text: str) -> None:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{TG}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
            },
        )
        if response.is_error:
            logger.error(
                "Failed to send Telegram message chat_id=%s status=%s body=%s",
                chat_id,
                response.status_code,
                response.text,
            )


async def process_transaction_and_notify(
    text: str,
    chat_id: int,
    message_id: int,
) -> str:
    try:
        reply = await process_transaction(text, chat_id, message_id)
        await send_telegram_message(chat_id, reply)
        logger.debug("Sent transaction follow-up chat_id=%s message_id=%s", chat_id, message_id)
        return reply
    except Exception:
        logger.exception(
            "Background transaction processing failed chat_id=%s message_id=%s",
            chat_id,
            message_id,
        )
        await send_telegram_message(chat_id, "Failed to log transaction. Please try again.")
        raise

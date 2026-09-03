import logging

import httpx

from config import TG

logger = logging.getLogger(__name__)


class TelegramWebhookError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def telegram_call(method: str, payload: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(f"{TG}/{method}", json=payload or {})
    data = response.json()
    if not data.get("ok"):
        logger.error("Telegram %s failed: %s", method, data)
        raise TelegramWebhookError(data.get("description", "Telegram API error"))
    return data


async def get_webhook_info() -> dict:
    logger.info("Fetching Telegram webhook info")
    data = await telegram_call("getWebhookInfo")
    return data.get("result", data)


async def set_webhook(
    url: str,
    *,
    secret_token: str | None = None,
    drop_pending_updates: bool = False,
) -> dict:
    body = {
        "url": url,
        "drop_pending_updates": drop_pending_updates,
    }
    if secret_token:
        body["secret_token"] = secret_token

    logger.info("Registering Telegram webhook url=%s", url)
    data = await telegram_call("setWebhook", body)
    return {
        "ok": True,
        "description": data.get("description"),
        "url": url,
    }


async def delete_webhook(*, drop_pending_updates: bool = False) -> dict:
    logger.info("Deleting Telegram webhook drop_pending_updates=%s", drop_pending_updates)
    data = await telegram_call(
        "deleteWebhook",
        {"drop_pending_updates": drop_pending_updates},
    )
    return {
        "ok": True,
        "description": data.get("description"),
    }


def format_webhook_info(info: dict) -> str:
    url = info.get("url") or "(none)"
    pending = info.get("pending_update_count", 0)
    last_error = info.get("last_error_message") or "none"
    last_error_date = info.get("last_error_date")
    ip = info.get("ip_address") or "-"
    max_connections = info.get("max_connections") or "-"

    lines = [
        "Webhook info",
        f"URL: {url}",
        f"Pending updates: {pending}",
        f"IP: {ip}",
        f"Max connections: {max_connections}",
        f"Last error: {last_error}",
    ]
    if last_error_date:
        lines.append(f"Last error date: {last_error_date}")
    return "\n".join(lines)

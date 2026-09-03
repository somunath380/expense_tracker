import json
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl

from db import (
    TRANSACTION_TYPES,
    delete_transaction_by_id,
    export_data,
    get_balance,
    get_or_create_category,
    get_transaction_by_id,
    import_data,
    insert_transaction,
    list_categories,
    list_transactions,
    update_transaction_by_id,
)
from telegram_webhook import (
    TelegramWebhookError,
    delete_webhook as remove_telegram_webhook,
    get_webhook_info as fetch_webhook_info,
    set_webhook as register_telegram_webhook,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["api"])

TransactionType = Literal["expense", "income", "adjustment"]


class TransactionCreate(BaseModel):
    chat_id: int
    type: TransactionType
    amount: float = Field(gt=0)
    category: str | None = None
    description: str | None = None
    source_text: str | None = None
    telegram_message_id: int | None = None


class TransactionUpdate(BaseModel):
    type: TransactionType | None = None
    amount: float | None = Field(default=None, gt=0)
    category: str | None = None
    description: str | None = None
    source_text: str | None = None
    created_at: str | None = None


class WebhookRegister(BaseModel):
    url: HttpUrl
    secret_token: str | None = None
    drop_pending_updates: bool = False


class WebhookDelete(BaseModel):
    drop_pending_updates: bool = False


def _serialize_transaction(row: dict) -> dict:
    return {
        "id": row["id"],
        "chat_id": row["chat_id"],
        "type": row["type"],
        "amount": row["amount"],
        "category": row.get("category_name"),
        "description": row.get("description"),
        "source_text": row.get("source_text"),
        "telegram_message_id": row.get("telegram_message_id"),
        "created_at": row.get("created_at"),
    }


@router.get("/transactions")
def get_transactions(
    chat_id: int | None = None,
    type: TransactionType | None = None,
    category: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    rows = list_transactions(
        chat_id=chat_id,
        tx_type=type,
        category=category,
        limit=limit,
        offset=offset,
    )
    return [_serialize_transaction(row) for row in rows]


@router.get("/transactions/{tx_id}")
def get_transaction(tx_id: int):
    row = get_transaction_by_id(tx_id)
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _serialize_transaction(row)


@router.post("/transactions", status_code=201)
def create_transaction(payload: TransactionCreate):
    category_id = None
    if payload.category:
        category_id = get_or_create_category(payload.category)

    tx_id = insert_transaction(
        payload.chat_id,
        payload.type,
        payload.amount,
        category_id=category_id,
        description=payload.description,
        source_text=payload.source_text,
        telegram_message_id=payload.telegram_message_id,
    )
    logger.info("API created transaction id=%s", tx_id)
    return _serialize_transaction(get_transaction_by_id(tx_id))


@router.patch("/transactions/{tx_id}")
def update_transaction(tx_id: int, payload: TransactionUpdate):
    if get_transaction_by_id(tx_id) is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    category_id = None
    if payload.category is not None:
        category_id = get_or_create_category(payload.category)

    if payload.type is not None and payload.type not in TRANSACTION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid transaction type")

    update_transaction_by_id(
        tx_id,
        amount=payload.amount,
        tx_type=payload.type,
        category_id=category_id,
        description=payload.description,
        source_text=payload.source_text,
        created_at=payload.created_at,
    )
    logger.info("API updated transaction id=%s", tx_id)
    return _serialize_transaction(get_transaction_by_id(tx_id))


@router.delete("/transactions/{tx_id}")
def delete_transaction(tx_id: int):
    if not delete_transaction_by_id(tx_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    logger.info("API deleted transaction id=%s", tx_id)
    return {"ok": True, "id": tx_id}


@router.get("/categories")
def get_categories():
    return list_categories()


@router.get("/balance")
def read_balance(chat_id: int):
    return {"chat_id": chat_id, "balance": get_balance(chat_id)}


@router.get("/export")
def export_transactions():
    data = export_data()
    filename = f"expense_tracker_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
async def import_transactions(
    file: UploadFile = File(...),
    replace: bool = Query(default=False, description="Replace all existing data"),
):
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Upload a .json file")

    try:
        payload = json.loads(await file.read())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="JSON must be an object with categories and transactions",
        )

    result = import_data(payload, replace=replace)
    return result


@router.get("/webhook")
async def get_webhook_info():
    try:
        return await fetch_webhook_info()
    except TelegramWebhookError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post("/webhook")
async def register_webhook(payload: WebhookRegister):
    try:
        return await register_telegram_webhook(
            str(payload.url),
            secret_token=payload.secret_token,
            drop_pending_updates=payload.drop_pending_updates,
        )
    except TelegramWebhookError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.delete("/webhook")
async def delete_webhook(payload: WebhookDelete | None = None):
    drop_pending = payload.drop_pending_updates if payload else False
    try:
        return await remove_telegram_webhook(drop_pending_updates=drop_pending)
    except TelegramWebhookError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

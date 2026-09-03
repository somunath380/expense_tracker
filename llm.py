import json
import logging
import re

from groq import Groq

from config import ANALYZE_MODEL, GROQ_API_KEY, LLM_MODEL

groq_client = Groq(api_key=GROQ_API_KEY)

logger = logging.getLogger(__name__)

PARSE_SYSTEM_PROMPT = """You extract expense and income transactions from user messages.
Return ONLY valid JSON with this shape:
{
  "is_transaction": true,
  "type": "expense",
  "amount": 150,
  "category": "Food",
  "description": "biriyani"
}

Rules:
- type is "expense" for spending, "income" for money received (salary, refund, etc.)
- amount must be a positive number in INR
- category: reuse an existing category when it fits; otherwise create a short Title Case name
- description: short cleaned item name
- if the message is not an expense or income, set is_transaction to false
- do not include markdown or extra text outside JSON"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def parse_transaction(text: str, existing_categories: list[str]) -> dict:
    categories_hint = ", ".join(existing_categories) if existing_categories else "none yet"
    logger.debug("Parsing transaction text=%r categories=%s", text, categories_hint)

    try:
        response = groq_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": PARSE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Existing categories: {categories_hint}\n"
                        f"Message: {text}"
                    ),
                },
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        parsed = _extract_json(response.choices[0].message.content or "{}")
    except Exception as exc:
        logger.exception("Groq parse_transaction failed text=%r", text)
        return {"error": str(exc)}

    if not parsed.get("is_transaction"):
        logger.debug("LLM marked message as non-transaction text=%r", text)
        return {"is_transaction": False}

    tx_type = parsed.get("type", "")
    amount = parsed.get("amount")
    category = parsed.get("category", "Other")
    description = parsed.get("description", "")

    if tx_type not in {"expense", "income"}:
        return {"error": f"Invalid transaction type: {tx_type}"}

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return {"error": f"Could not parse amount: {amount}"}

    if amount <= 0:
        return {"error": "Amount must be greater than zero"}

    result = {
        "is_transaction": True,
        "type": tx_type,
        "amount": amount,
        "category": category.strip().title() if category else "Other",
        "description": str(description).strip() or "Unknown",
    }
    logger.info(
        "Parsed transaction type=%s amount=%s category=%s description=%s",
        result["type"],
        result["amount"],
        result["category"],
        result["description"],
    )
    return result


def analyze_month(aggregates: dict) -> dict:
    month_name = datetime_month_name(aggregates["year"], aggregates["month"])
    logger.info(
        "Analyzing month year=%s month=%s expense_total=%s",
        aggregates["year"],
        aggregates["month"],
        aggregates["expense_total"],
    )
    categories_text = "\n".join(
        f"- {item['category']}: ₹{item['total']:,.0f}"
        for item in aggregates["categories"]
    ) or "- No expenses recorded"

    prompt = f"""Write a short spending review for {month_name}.
Use ONLY the data below. Do not invent numbers.

Total expenses: ₹{aggregates['expense_total']:,.0f}
Previous month expenses: ₹{aggregates['previous_month_total']:,.0f}
Current balance: ₹{aggregates['balance']:,.0f}

By category:
{categories_text}

Highlight top categories, month-over-month change, and one practical tip."""

    try:
        response = groq_client.chat.completions.create(
            model=ANALYZE_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a concise personal finance assistant. Use INR (₹).",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        return {"text": (response.choices[0].message.content or "").strip()}
    except Exception as exc:
        logger.exception(
            "Groq analyze_month failed year=%s month=%s",
            aggregates["year"],
            aggregates["month"],
        )
        return {"error": str(exc)}


def datetime_month_name(year: int, month: int) -> str:
    from datetime import datetime

    return datetime(year, month, 1).strftime("%B %Y")

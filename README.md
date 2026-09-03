# Expense Tracker Bot

A personal expense tracker powered by a **Telegram bot** and a **FastAPI** webhook server. Log spending by voice or text, track your INR balance, view summaries by category, and get monthly spending analysis — all from Telegram.

## How it works

1. You send a **voice note** or **text message** (e.g. `150 biriyani`) to your Telegram bot.
2. The server replies immediately (Telegram expects a response within ~5 seconds).
3. A **background task** processes the message:
   - Voice notes are transcribed with **Groq Whisper**.
   - Text is parsed with **Groq LLM** into amount, category, and description.
   - The transaction is saved to **Turso** (libSQL).
4. You receive a follow-up confirmation with the transaction id and updated balance.

Summaries and totals are computed from the database. The LLM is used only for parsing natural language and writing monthly analysis narratives — not for math.

## Features

- Voice and text expense logging
- Automatic categorization (LLM reuses or creates categories)
- Income tracking (e.g. `salary 50000`)
- Balance ledger with manual sync via `/balance`
- Spending summaries by date range
- Monthly AI spending analysis
- Edit and delete transactions

---

## Telegram commands

### Getting started

| Command | Description |
|---|---|
| `/start` | Welcome message and quick intro |
| `/help` | List all commands and usage examples |

### Logging expenses

Send a **voice note** or type a message in natural language. No command needed.

| Example | Result |
|---|---|
| `150 biriyani` | Logs ₹150 expense under Food (or similar category) |
| `360 on meter box` | Logs ₹360 with an appropriate category |
| `salary 50000` | Records ₹50,000 as income |

You will first get `"Got it, logging..."` (or `"Voice note received."` for voice), then a confirmation like:

```text
Logged ₹150 on biriyani (Food). Id 12. Balance ₹44,850.
```

If parsing fails, the bot replies with the error reason and the source text so you can retry by typing.

### Balance

| Command | Description |
|---|---|
| `/balance` | Show your current computed balance |
| `/balance 45000` | Sync balance to exactly ₹45,000 (creates an adjustment entry) |

Balance is calculated from all transactions:

```text
balance = income + adjustments − expenses
```

### Summaries

| Command | Description |
|---|---|
| `/summary` | Expenses by category for **this calendar month** (default) |
| `/summary today` | Expenses for today |
| `/summary yesterday` | Expenses for yesterday |
| `/summary week` | Expenses for this week (Monday–Sunday) |
| `/summary month` | Same as `/summary` — this calendar month |
| `/summary 1 Sep to 15 Sep` | Custom date range |

Shows category breakdown, total spent, and current balance.

### Analysis

| Command | Description |
|---|---|
| `/analyze` | AI-written review of **this calendar month's** spending |
| `/analyze 2026-08` | Analyze a specific month (`YYYY-MM`) |

Uses SQL for totals; the LLM only writes the human-readable summary.

### Transaction history

| Command | Description |
|---|---|
| `/last` | Show the 5 most recent transactions with ids |

Use transaction ids for edit and delete commands below.

### Delete

| Command | Description |
|---|---|
| `/delete last` | Delete your most recent transaction |
| `/delete 12` | Delete transaction by id (from `/last`) |

Balance is recalculated automatically after deletion.

### Edit

| Command | Description |
|---|---|
| `/edit last 200 biriyani` | Re-parse and update the last transaction |
| `/edit 12 amount 200` | Change only the amount on transaction #12 |
| `/edit 12 200 biriyani` | Re-parse and update transaction #12 |

### Webhooks

| Command | Description |
|---|---|
| `/getwebhook` | Show the currently registered Telegram webhook |
| `/setwebhook https://your-url/` | Register or update the webhook URL |

---

## Setup

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)
- Telegram bot token ([BotFather](https://t.me/BotFather))
- Groq API key ([console.groq.com](https://console.groq.com))

### Install and run

```bash
cd expense_tracker
uv venv .venv
uv sync
cp .env.example .env
# Edit .env with your BOT_TOKEN and GROQ_API_KEY
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Or use the **Run FastAPI Server** launch configuration in `.vscode/launch.json`.

### Environment variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token |
| `GROQ_API_KEY` | Groq API key (Whisper + LLM) |
| `WHISPER_MODEL` | Speech-to-text model (default: `whisper-large-v3-turbo`) |
| `LLM_MODEL` | Model for parsing expenses (default: `openai/gpt-oss-20b`) |
| `ANALYZE_MODEL` | Model for monthly analysis (default: `openai/gpt-oss-120b`) |
| `TURSO_DATABASE_URL` | Turso/libSQL database URL |
| `TURSO_AUTH_TOKEN` | Turso database auth token |
| `LOG_LEVEL` | Logging level: `INFO` or `DEBUG` |

### Telegram webhook (ngrok)

Expose your local server and register the webhook with Telegram:

```bash
ngrok http 8000
```

Check current webhook:

```bash
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

Register or update webhook (use your ngrok HTTPS URL; route is `/`):

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://YOUR-NGROK-URL/"
```

Remove webhook:

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
```

Re-register the webhook whenever ngrok restarts and gives you a new URL.

---

## REST API

Interactive docs: `http://localhost:8000/docs`

### Transactions

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/transactions` | List transactions (`chat_id`, `type`, `category`, `limit`, `offset`) |
| `GET` | `/api/transactions/{id}` | Get one transaction |
| `POST` | `/api/transactions` | Create a transaction |
| `PATCH` | `/api/transactions/{id}` | Update a transaction |
| `DELETE` | `/api/transactions/{id}` | Delete a transaction |

Create example:

```bash
curl -X POST http://localhost:8000/api/transactions \
  -H "Content-Type: application/json" \
  -d '{"chat_id": 123, "type": "expense", "amount": 150, "category": "Food", "description": "biriyani"}'
```

### Other

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/categories` | List categories |
| `GET` | `/api/balance?chat_id=123` | Computed balance |

### Import / export

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/export` | Download all categories and transactions as JSON |
| `POST` | `/api/import` | Upload a JSON export file (`replace=true` wipes existing data first) |

```bash
curl -o backup.json http://localhost:8000/api/export

curl -X POST "http://localhost:8000/api/import?replace=false" \
  -F "file=@backup.json"
```

### Telegram webhooks

The bot webhook route is `POST /`. Register a public HTTPS URL that points there (ngrok or Render).

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/webhook` | Current webhook (`getWebhookInfo`) |
| `POST` | `/api/webhook` | Register / update webhook (`setWebhook`) |
| `DELETE` | `/api/webhook` | Remove webhook (`deleteWebhook`) |

```bash
# View current webhook
curl http://localhost:8000/api/webhook

# Register (use your public URL; path is /)
curl -X POST http://localhost:8000/api/webhook \
  -H "Content-Type: application/json" \
  -d '{"url": "https://YOUR-PUBLIC-URL/"}'

# Delete
curl -X DELETE http://localhost:8000/api/webhook \
  -H "Content-Type: application/json" \
  -d '{"drop_pending_updates": false}'
```

---

## Project structure

| File | Purpose |
|---|---|
| `main.py` | FastAPI webhook handler |
| `api.py` | REST CRUD, import, and export endpoints |
| `handlers.py` | Telegram command routing |
| `pipeline.py` | Parse → save → confirm flow |
| `voice.py` | Voice download and transcription pipeline |
| `transcribe.py` | Groq Whisper integration |
| `llm.py` | Groq LLM parse and analyze |
| `db.py` | Turso/libSQL schema and queries |
| `config.py` | Environment configuration |

---

## Suggested first steps

1. `/balance 45000` — set your starting balance
2. Send `150 biriyani` or a voice note
3. `/summary` — verify the expense appears
4. `/balance` — confirm balance updated
5. At month end: `/analyze`

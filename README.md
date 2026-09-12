# AG-UI + AG Grid + FastAPI Local POC

A fully local conversational data POC. No AWS, Bedrock, database, API key, or cloud account is required.

## What it demonstrates

- React frontend
- AG Grid customer/transaction tables
- FastAPI backend
- AG-UI-style event streaming over Server-Sent Events (SSE)
- Natural-language prompt routing using deterministic local rules
- 12 dummy customers and 30 dummy transactions
- Chat prompts that change the grid/query result
- Docker Compose for one-command startup

> Note: This POC uses the AG-UI event/message pattern over SSE and keeps the prompt interpretation local/deterministic. It is intentionally AWS/LLM-free so the UI flow can be validated first. A real AG-UI agent/LLM can be plugged into the same boundary later.

## Run with Docker (optional)

Prerequisite: Docker Desktop.

```bash
docker compose up --build
```

Open:

http://localhost:3000

API health:

http://localhost:8000/health

## Run locally without Docker

Docker is not required. If Docker Desktop is unavailable, run the backend and frontend directly with the commands below. The Vite proxy keeps the frontend API calls on the same `/api` path in both modes.

Backend:

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal (normally http://localhost:5173).

The UI starts in dark mode. Use the Dark/Light control in the header to switch themes; the selection is remembered in the browser.

## Example prompts

- Show all active customers
- Show customers with balance greater than 10000
- Show high risk customers
- Show all transactions
- Show transactions for customer 1003
- Show pending transactions
- How many active customers do we have?
- What is the total balance?
- Give me details for customer 1005

## Architecture

```text
                    LOCAL ONLY
+-------------+     SSE/HTTP     +----------------+
| React +     | <--------------> | FastAPI        |
| AG Grid     |                  | Prompt Router  |
| Chat UI     |                  | Dummy Data     |
+-------------+                  +----------------+
                                        |
                                  customers.json
                                  transactions.json
```

## Replacing dummy logic later

The frontend only expects a streamed agent response containing text and optional grid data. The backend prompt router can later be replaced by:

FastAPI -> AG-UI agent -> Bedrock/Claude/OpenAI -> tools/RAG/database

No AWS credentials are needed for this POC.

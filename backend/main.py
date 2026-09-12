import asyncio
import json
import re
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="AG-UI Local POC")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CUSTOMERS = [
    {"id": 1001, "name": "John Smith", "email": "john.smith@example.com", "status": "Active", "risk": "Low", "balance": 12500, "city": "New York"},
    {"id": 1002, "name": "Sarah Wilson", "email": "sarah.wilson@example.com", "status": "Active", "risk": "Low", "balance": 8700, "city": "Chicago"},
    {"id": 1003, "name": "Michael Brown", "email": "michael.brown@example.com", "status": "Inactive", "risk": "Medium", "balance": 15300, "city": "Dallas"},
    {"id": 1004, "name": "Emily Davis", "email": "emily.davis@example.com", "status": "Active", "risk": "High", "balance": 22400, "city": "Boston"},
    {"id": 1005, "name": "David Miller", "email": "david.miller@example.com", "status": "Active", "risk": "Medium", "balance": 9800, "city": "Seattle"},
    {"id": 1006, "name": "Olivia Garcia", "email": "olivia.garcia@example.com", "status": "Active", "risk": "Low", "balance": 18200, "city": "Austin"},
    {"id": 1007, "name": "James Martinez", "email": "james.martinez@example.com", "status": "Inactive", "risk": "High", "balance": 6400, "city": "Phoenix"},
    {"id": 1008, "name": "Sophia Anderson", "email": "sophia.anderson@example.com", "status": "Active", "risk": "Low", "balance": 31200, "city": "Denver"},
    {"id": 1009, "name": "Daniel Thomas", "email": "daniel.thomas@example.com", "status": "Active", "risk": "Medium", "balance": 11900, "city": "Atlanta"},
    {"id": 1010, "name": "Ava Taylor", "email": "ava.taylor@example.com", "status": "Active", "risk": "High", "balance": 27500, "city": "Miami"},
    {"id": 1011, "name": "William Moore", "email": "william.moore@example.com", "status": "Inactive", "risk": "Medium", "balance": 7200, "city": "Portland"},
    {"id": 1012, "name": "Isabella Jackson", "email": "isabella.jackson@example.com", "status": "Active", "risk": "Low", "balance": 14600, "city": "San Diego"},
]

TRANSACTIONS = [
    {"id": "TX-2001", "customer_id": 1001, "type": "Payment", "amount": 2400, "status": "Completed", "date": "2026-09-01"},
    {"id": "TX-2002", "customer_id": 1001, "type": "Deposit", "amount": 5000, "status": "Completed", "date": "2026-09-03"},
    {"id": "TX-2003", "customer_id": 1002, "type": "Payment", "amount": 1200, "status": "Pending", "date": "2026-09-04"},
    {"id": "TX-2004", "customer_id": 1002, "type": "Withdrawal", "amount": 800, "status": "Completed", "date": "2026-09-05"},
    {"id": "TX-2005", "customer_id": 1003, "type": "Payment", "amount": 3100, "status": "Failed", "date": "2026-09-01"},
    {"id": "TX-2006", "customer_id": 1003, "type": "Deposit", "amount": 6000, "status": "Completed", "date": "2026-09-06"},
    {"id": "TX-2007", "customer_id": 1004, "type": "Payment", "amount": 4500, "status": "Pending", "date": "2026-09-06"},
    {"id": "TX-2008", "customer_id": 1004, "type": "Payment", "amount": 1800, "status": "Completed", "date": "2026-09-07"},
    {"id": "TX-2009", "customer_id": 1005, "type": "Deposit", "amount": 2500, "status": "Completed", "date": "2026-09-02"},
    {"id": "TX-2010", "customer_id": 1005, "type": "Payment", "amount": 950, "status": "Completed", "date": "2026-09-07"},
    {"id": "TX-2011", "customer_id": 1006, "type": "Payment", "amount": 2100, "status": "Completed", "date": "2026-09-02"},
    {"id": "TX-2012", "customer_id": 1006, "type": "Deposit", "amount": 7000, "status": "Completed", "date": "2026-09-08"},
    {"id": "TX-2013", "customer_id": 1007, "type": "Withdrawal", "amount": 1300, "status": "Pending", "date": "2026-09-08"},
    {"id": "TX-2014", "customer_id": 1007, "type": "Payment", "amount": 2400, "status": "Failed", "date": "2026-09-09"},
    {"id": "TX-2015", "customer_id": 1008, "type": "Deposit", "amount": 10000, "status": "Completed", "date": "2026-09-03"},
    {"id": "TX-2016", "customer_id": 1008, "type": "Payment", "amount": 3300, "status": "Completed", "date": "2026-09-09"},
    {"id": "TX-2017", "customer_id": 1009, "type": "Payment", "amount": 1700, "status": "Pending", "date": "2026-09-04"},
    {"id": "TX-2018", "customer_id": 1009, "type": "Deposit", "amount": 4000, "status": "Completed", "date": "2026-09-10"},
    {"id": "TX-2019", "customer_id": 1010, "type": "Payment", "amount": 5200, "status": "Completed", "date": "2026-09-04"},
    {"id": "TX-2020", "customer_id": 1010, "type": "Payment", "amount": 2800, "status": "Pending", "date": "2026-09-10"},
    {"id": "TX-2021", "customer_id": 1011, "type": "Withdrawal", "amount": 600, "status": "Completed", "date": "2026-09-03"},
    {"id": "TX-2022", "customer_id": 1011, "type": "Payment", "amount": 1100, "status": "Failed", "date": "2026-09-05"},
    {"id": "TX-2023", "customer_id": 1012, "type": "Deposit", "amount": 4500, "status": "Completed", "date": "2026-09-05"},
    {"id": "TX-2024", "customer_id": 1012, "type": "Payment", "amount": 1500, "status": "Completed", "date": "2026-09-08"},
    {"id": "TX-2025", "customer_id": 1001, "type": "Payment", "amount": 900, "status": "Pending", "date": "2026-09-10"},
    {"id": "TX-2026", "customer_id": 1004, "type": "Deposit", "amount": 3000, "status": "Completed", "date": "2026-09-10"},
    {"id": "TX-2027", "customer_id": 1006, "type": "Payment", "amount": 1200, "status": "Completed", "date": "2026-09-11"},
    {"id": "TX-2028", "customer_id": 1008, "type": "Payment", "amount": 4100, "status": "Pending", "date": "2026-09-11"},
    {"id": "TX-2029", "customer_id": 1010, "type": "Deposit", "amount": 8000, "status": "Completed", "date": "2026-09-11"},
    {"id": "TX-2030", "customer_id": 1012, "type": "Payment", "amount": 700, "status": "Pending", "date": "2026-09-11"},
]

class PromptRequest(BaseModel):
    prompt: str

def customer_by_id(cid: int):
    return next((c for c in CUSTOMERS if c["id"] == cid), None)

def detect_customer_id(prompt: str):
    m = re.search(r"\b(10\d{2})\b", prompt)
    return int(m.group(1)) if m else None

def route_prompt(prompt: str) -> dict[str, Any]:
    p = prompt.lower().strip()

    # Customer-specific detail
    cid = detect_customer_id(p)
    if cid:
        c = customer_by_id(cid)
        if c and any(x in p for x in ["detail", "details", "information", "info", "customer"]):
            return {
                "text": f"Here are the details for {c['name']} (customer {cid}).",
                "grid": "customers",
                "rows": [c],
            }
        if any(x in p for x in ["transaction", "transactions", "tx"]):
            rows = [t for t in TRANSACTIONS if t["customer_id"] == cid]
            return {
                "text": f"I found {len(rows)} transactions for {c['name']}.",
                "grid": "transactions",
                "rows": rows,
            }

    if "transaction" in p:
        rows = TRANSACTIONS[:]
        if "pending" in p:
            rows = [t for t in rows if t["status"].lower() == "pending"]
            return {"text": f"I found {len(rows)} pending transactions.", "grid": "transactions", "rows": rows}
        if "failed" in p:
            rows = [t for t in rows if t["status"].lower() == "failed"]
            return {"text": f"I found {len(rows)} failed transactions.", "grid": "transactions", "rows": rows}
        return {"text": f"I found {len(rows)} transactions in the dummy dataset.", "grid": "transactions", "rows": rows}

    if "active" in p and "customer" in p:
        rows = [c for c in CUSTOMERS if c["status"] == "Active"]
        return {"text": f"There are {len(rows)} active customers.", "grid": "customers", "rows": rows}

    if "inactive" in p and "customer" in p:
        rows = [c for c in CUSTOMERS if c["status"] == "Inactive"]
        return {"text": f"There are {len(rows)} inactive customers.", "grid": "customers", "rows": rows}

    if "high risk" in p or "high-risk" in p:
        rows = [c for c in CUSTOMERS if c["risk"] == "High"]
        return {"text": f"I found {len(rows)} high-risk customers.", "grid": "customers", "rows": rows}

    if "medium risk" in p:
        rows = [c for c in CUSTOMERS if c["risk"] == "Medium"]
        return {"text": f"I found {len(rows)} medium-risk customers.", "grid": "customers", "rows": rows}

    m = re.search(r"(?:greater|more|above|over)\s*(?:than)?\s*\$?\s*(\d[\d,]*)", p)
    if m and "balance" in p:
        amount = int(m.group(1).replace(",", ""))
        rows = [c for c in CUSTOMERS if c["balance"] > amount]
        return {"text": f"I found {len(rows)} customers with balance greater than ${amount:,.0f}.", "grid": "customers", "rows": rows}

    if "how many" in p and "customer" in p:
        return {"text": f"The dummy dataset contains {len(CUSTOMERS)} customers.", "grid": "customers", "rows": CUSTOMERS}

    if "total balance" in p or ("balance" in p and "total" in p):
        total = sum(c["balance"] for c in CUSTOMERS)
        return {"text": f"The total balance across all dummy customers is ${total:,.0f}.", "grid": "customers", "rows": CUSTOMERS}

    if "customer" in p:
        return {"text": f"I found {len(CUSTOMERS)} customers in the dummy dataset.", "grid": "customers", "rows": CUSTOMERS}

    return {
        "text": "I can query the local dummy dataset. Try: “Show active customers”, “Show high risk customers”, “Show pending transactions”, “Show transactions for customer 1003”, or “Show customers with balance greater than 10000”.",
        "grid": None,
        "rows": [],
    }

def sse(event: str, data: dict):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

@app.get("/health")
def health():
    return {"status": "ok", "mode": "local-dummy-data"}

@app.get("/api/customers")
def customers():
    return CUSTOMERS

@app.get("/api/transactions")
def transactions():
    return TRANSACTIONS

@app.post("/api/chat")
async def chat(req: PromptRequest):
    result = route_prompt(req.prompt)

    async def stream():
        # AG-UI-style event sequence for a local POC.
        yield sse("RUN_STARTED", {"threadId": "local-poc", "runId": "local-run"})
        await asyncio.sleep(0.08)
        yield sse("TEXT_MESSAGE_START", {"messageId": "assistant-1", "role": "assistant"})
        await asyncio.sleep(0.08)
        yield sse("TEXT_MESSAGE_CONTENT", {"messageId": "assistant-1", "delta": result["text"]})
        await asyncio.sleep(0.08)
        yield sse("TEXT_MESSAGE_END", {"messageId": "assistant-1"})

        if result["grid"]:
            await asyncio.sleep(0.08)
            yield sse("CUSTOM_DATA", {
                "type": "grid_data",
                "grid": result["grid"],
                "rows": result["rows"],
            })

        yield sse("RUN_FINISHED", {"threadId": "local-poc", "runId": "local-run"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )

from __future__ import annotations

from datetime import datetime
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
import re
from llm import enabled as llm_enabled, reply as llm_reply

app = FastAPI(title="Velora Assist API", version="1.0.0")
ROOT = Path(__file__).resolve().parent

# Seeded fictional store data. In production these functions are adapters to WooCommerce/POS APIs.
PRODUCTS = [
    {"id": "vel-jacket", "name": "Everyday Overshirt", "category": "Outerwear", "price": 54, "description": "Soft cotton overshirt for everyday layering.", "image": "🧥", "variants": {"S": 8, "M": 3, "L": 0, "XL": 5}},
    {"id": "vel-knit", "name": "Merino Knit Polo", "category": "Knitwear", "price": 48, "description": "Lightweight merino blend polo in three colours.", "image": "🧶", "variants": {"S": 4, "M": 12, "L": 7, "XL": 2}},
    {"id": "vel-runner", "name": "Cloud Runner", "category": "Footwear", "price": 72, "description": "Comfort-first everyday running sneaker.", "image": "👟", "variants": {"40": 2, "41": 0, "42": 6, "43": 4}},
    {"id": "vel-tee", "name": "Core Cotton Tee", "category": "Essentials", "price": 22, "description": "Premium 240gsm cotton t-shirt.", "image": "👕", "variants": {"S": 15, "M": 19, "L": 9, "XL": 6}},
]
ORDERS = {
    "VL-1042": {"customer_phone": "03001234567", "customer_name": "Ayesha Khan", "status": "In transit", "carrier": "TCS", "tracking": "TCS-887302", "eta": "Tomorrow, before 6 PM", "ordered_on": "2026-09-19", "items": ["Everyday Overshirt · M"], "total": 54, "delivered": False},
    "VL-1048": {"customer_phone": "03001234567", "customer_name": "Ayesha Khan", "status": "Delivered", "carrier": "Leopards", "tracking": "LP-901200", "eta": "Delivered on 20 Sep", "ordered_on": "2026-09-12", "items": ["Core Cotton Tee · M", "Merino Knit Polo · M"], "total": 70, "delivered": True},
    "VL-1051": {"customer_phone": "03112223333", "customer_name": "Hassan Ali", "status": "Processing", "carrier": "Not assigned", "tracking": None, "eta": "Dispatches within 24 hours", "ordered_on": "2026-09-21", "items": ["Cloud Runner · 42"], "total": 72, "delivered": False},
}
AUDIT: list[dict[str, Any]] = []
HANDOFFS: list[dict[str, Any]] = []
DRAFTS: list[dict[str, Any]] = []

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=800)
    customer_phone: str | None = None
    conversation: list[dict[str, str]] = Field(default_factory=list)

class HandoffUpdate(BaseModel):
    status: str = Field(pattern="^(Open|In progress|Resolved)$")

class ToolResult(BaseModel):
    tool: str
    data: Any


def audit(tool: str, payload: dict[str, Any]) -> None:
    AUDIT.insert(0, {"tool": tool, "payload": payload, "at": datetime.now().strftime("%H:%M")})
    del AUDIT[50:]


def normalize(text: str) -> str:
    text = text.lower().replace("'", "")
    substitutions = {
        "jacket": "overshirt", "shirt": "overshirt", "sneakers": "runner", "shoes": "runner",
        "t shirt": "tee", "tshirt": "tee", "parcel": "order", "delivery": "tracking",
    }
    for old, new in substitutions.items(): text = text.replace(old, new)
    return re.sub(r"[^a-z0-9# -]", " ", text)


def search_products(query: str, budget: int | None = None) -> list[dict]:
    terms = set(normalize(query).split()) - {"show", "me", "something", "under", "below", "than", "i", "need", "a", "an"}
    found = []
    for product in PRODUCTS:
        blob = set(normalize(" ".join([product["name"], product["category"], product["description"]])).split())
        if (not terms or terms.intersection(blob)) and (budget is None or product["price"] <= budget): found.append(product)
    audit("search_products", {"query": query, "budget": budget, "matches": len(found)})
    return found


def product_from_message(message: str) -> dict | None:
    text = set(normalize(message).split())
    best = None
    for product in PRODUCTS:
        score = len(text.intersection(set(normalize(product["name"]).split())))
        if score and (best is None or score > best[0]): best = (score, product)
    return best[1] if best else None


def get_variant_stock(product: dict, size: str) -> dict:
    stock = product["variants"].get(size.upper())
    result = {"product": product["name"], "size": size.upper(), "stock": stock, "available": bool(stock and stock > 0)}
    audit("get_variant_stock", result)
    return result


def find_order(message: str) -> str | None:
    hit = re.search(r"(?:vl[- ]?)?(10\d{2})", message.lower())
    return f"VL-{hit.group(1)}" if hit else None


def verified_order(order_id: str, phone: str | None) -> dict | None:
    order = ORDERS.get(order_id)
    digits = re.sub(r"\D", "", phone or "")
    return order if order and digits[-10:] == re.sub(r"\D", "", order["customer_phone"])[-10:] else None


def card(kind: str, data: dict) -> dict:
    return {"type": kind, "data": data}


def assistant_response(request: ChatRequest) -> tuple[str, list[ToolResult], list[dict]]:
    message, lower = request.message.strip(), normalize(request.message)
    tools: list[ToolResult] = []; cards: list[dict] = []
    if any(x in lower for x in ["human", "representative", "agent", "complaint", "talk to someone"]):
        handoff = {"ticket": f"HS-{len(HANDOFFS)+301}", "reason": message, "phone": request.customer_phone or "Not provided", "status": "Open", "created_at": datetime.now().strftime("%d %b, %H:%M")}
        HANDOFFS.insert(0, handoff); audit("create_human_handoff", handoff); tools.append(ToolResult(tool="create_human_handoff", data=handoff)); cards.append(card("handoff", handoff))
        return f"I’ve opened ticket {handoff['ticket']}. A human representative has been notified and will continue from this conversation.", tools, cards

    order_id = find_order(message); wants_return = any(x in lower for x in ["return", "refund", "exchange"]); wants_tracking = any(x in lower for x in ["track", "where is", "status", "tracking", "order"])
    if order_id and (wants_return or wants_tracking):
        order = verified_order(order_id, request.customer_phone)
        if not order: return "For privacy, enter the same phone number used for the order. I can only reveal order details after verification.", tools, cards
        if wants_return:
            # Demo policy: orders marked delivered are returnable within 14 days of delivery.
            eligible = order["delivered"]
            data = {"order": order_id, "eligible": eligible, "window": "14 days after delivery", "items": order["items"]}; audit("get_return_eligibility", data); tools.append(ToolResult(tool="get_return_eligibility", data=data)); cards.append(card("return", data))
            return (f"{order_id} is eligible for a return. Select the item and reason in a real WhatsApp flow to create the request." if eligible else f"{order_id} is still {order['status'].lower()}, so a return cannot start yet. I can connect you to support if needed."), tools, cards
        data = {"order": order_id, "status": order["status"], "carrier": order["carrier"], "tracking": order["tracking"], "eta": order["eta"], "items": order["items"], "total": order["total"]}; audit("get_order_status", data); tools.append(ToolResult(tool="get_order_status", data=data)); cards.append(card("order", data))
        tracking = f" Tracking: {order['tracking']}." if order['tracking'] else ""
        return f"Order {order_id} is {order['status'].lower()}. {order['eta']}.{tracking}", tools, cards

    if any(x in lower for x in ["return policy", "returns policy", "how do i return"]):
        data = {"window": "14 days after delivery", "condition": "unused items with tags"}; audit("get_return_policy", data); tools.append(ToolResult(tool="get_return_policy", data=data)); cards.append(card("policy", data))
        return "Returns are accepted within 14 days after delivery for unused items with original tags. Share a verified order number to check eligibility.", tools, cards

    budget_match = re.search(r"(?:under|below|less than)\s*\$?(\d+)", lower); budget = int(budget_match.group(1)) if budget_match else None
    product = product_from_message(message)
    size_words = {"extra small": "XS", "small": "S", "medium": "M", "large": "L", "extra large": "XL"}
    named_size = next((value for word, value in size_words.items() if word in lower), None)
    size_match = re.search(r"\b(xs|s|m|l|xl|40|41|42|43)\b", lower)
    wants_stock = any(x in lower for x in ["size", "available", "stock", "have", "medium", "small", "large"])
    if product and wants_stock and (size_match or named_size):
        result = get_variant_stock(product, named_size or size_match.group(1).upper()); tools.append(ToolResult(tool="get_variant_stock", data=result)); cards.append(card("stock", {**result, "price": product["price"], "image": product["image"]}))
        if result["stock"] is None: return f"{product['name']} does not come in size {result['size']}. Available options are {', '.join(product['variants'])}.", tools, cards
        if result["available"]: return f"Yes — {product['name']} in size {result['size']} is available. It costs ${product['price']}.", tools, cards
        available = ', '.join(k for k,v in product['variants'].items() if v > 0); return f"{product['name']} in size {result['size']} is out of stock. Available options: {available}.", tools, cards

    if budget is not None or any(x in lower for x in ["recommend", "show", "looking for", "product", "buy", "suggest"]):
        results = search_products(message, budget); tools.append(ToolResult(tool="search_products", data=[{"name": p["name"], "price": p["price"]} for p in results])); cards += [card("product", p) for p in results[:3]]
        if results:
            listed = '; '.join(f"{p['name']} (${p['price']})" for p in results[:3]); return (f"Here are options under ${budget}: " if budget else "Here are relevant options: ") + listed + ". Ask about a size and I’ll check stock.", tools, cards
        return "I couldn’t find a catalog match. Try overshirt, knit polo, runner, or tee.", tools, cards

    return "I can check exact product stock, track a verified order, check returns, recommend by budget, or connect you to a human representative.", tools, cards

@app.get("/")
def home(): return FileResponse(ROOT / "index.html")
@app.post("/api/chat")
def chat(request: ChatRequest):
    # The LLM decides language and which approved tool to call; the tool layer owns all facts.
    if llm_enabled():
        def product_by_id(product_id: str) -> dict:
            return next((p for p in PRODUCTS if p["id"] == product_id), {"error": "Product not found"})
        def stock_tool(product_id: str, size: str) -> dict:
            product = product_by_id(product_id)
            return product if "error" in product else get_variant_stock(product, size)
        def order_tool(order_number: str, customer_phone: str) -> dict:
            order = verified_order(order_number.upper(), customer_phone)
            data = {"order": order_number.upper(), "status": order["status"], "carrier": order["carrier"], "tracking": order["tracking"], "eta": order["eta"]} if order else {"error": "Order could not be verified"}
            audit("get_order_status", data); return data
        def return_tool(order_number: str, customer_phone: str) -> dict:
            order = verified_order(order_number.upper(), customer_phone)
            data = {"order": order_number.upper(), "eligible": bool(order and order["delivered"]), "policy": "14 days after delivery"} if order else {"error": "Order could not be verified"}
            audit("get_return_eligibility", data); return data
        def handoff_tool(reason: str) -> dict:
            item = {"ticket": f"HS-{len(HANDOFFS)+301}", "reason": reason, "phone": request.customer_phone or "Not provided", "status": "Open", "created_at": datetime.now().strftime("%d %b, %H:%M")}
            HANDOFFS.insert(0, item); audit("create_human_handoff", item); return item
        text, calls = llm_reply(request.message, request.customer_phone, {"search_products": search_products, "get_variant_stock": stock_tool, "get_order_status": order_tool, "get_return_eligibility": return_tool, "create_human_handoff": handoff_tool})
        return {"reply": text, "tool_calls": calls, "cards": []}
    reply, tools, cards = assistant_response(request)
    return {"reply": reply, "tool_calls": [x.model_dump() for x in tools], "cards": cards}

@app.get("/api/catalog")
def catalog(): return PRODUCTS
@app.get("/api/ops")
def ops(): return {"handoffs": HANDOFFS, "audit": AUDIT, "drafts": DRAFTS}
@app.patch("/api/handoffs/{ticket}")
def update_handoff(ticket: str, update: HandoffUpdate):
    item = next((h for h in HANDOFFS if h['ticket'] == ticket), None)
    if not item: raise HTTPException(status_code=404, detail="Ticket not found")
    item['status'] = update.status; audit("update_handoff", {"ticket": ticket, "status": update.status}); return item
@app.post("/api/reminder-drafts")
def reminder_draft():
    draft = {"id": f"DR-{len(DRAFTS)+41}", "status": "Needs owner approval", "message": "Hi Ayesha, your Everyday Overshirt is still waiting in your cart. Would you like help choosing a size?", "created_at": datetime.now().strftime("%d %b, %H:%M")}
    DRAFTS.insert(0, draft); audit("create_followup_draft", draft); return draft
app.mount("/static", StaticFiles(directory=ROOT), name="static")








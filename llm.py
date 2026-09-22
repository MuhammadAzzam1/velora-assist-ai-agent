"""Optional Groq function-calling adapter.

The deterministic router remains available for a free, no-key demo. When GROQ_API_KEY
is set, this module can replace only the language-understanding layer. Store facts still
come exclusively from the approved backend tools.
"""
from __future__ import annotations
import json, os
from typing import Callable

TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "search_products", "description": "Search the product catalog and optionally filter by max budget.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "budget": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_variant_stock", "description": "Check exact product size/variant availability.", "parameters": {"type": "object", "properties": {"product_id": {"type": "string"}, "size": {"type": "string"}}, "required": ["product_id", "size"]}}},
    {"type": "function", "function": {"name": "get_order_status", "description": "Get an order only after customer phone verification.", "parameters": {"type": "object", "properties": {"order_number": {"type": "string"}, "customer_phone": {"type": "string"}}, "required": ["order_number", "customer_phone"]}}},
    {"type": "function", "function": {"name": "get_return_eligibility", "description": "Check return eligibility only after customer phone verification.", "parameters": {"type": "object", "properties": {"order_number": {"type": "string"}, "customer_phone": {"type": "string"}}, "required": ["order_number", "customer_phone"]}}},
    {"type": "function", "function": {"name": "create_human_handoff", "description": "Create a human support ticket when the customer explicitly requests it or the request needs human judgement.", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
]

SYSTEM = """You are Velora Store Support. You help with catalog discovery, variant stock,
verified order tracking, returns, and human handoff. You must use tools for every factual
claim about products, stock, orders, delivery, or returns. Never invent facts. Never reveal
an order without the supplied customer phone. Keep answers clear and concise."""

def enabled() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))

def reply(message: str, phone: str | None, tools: dict[str, Callable]) -> tuple[str, list[dict]]:
    """Run one tool-call loop. Called only when GROQ_API_KEY is configured."""
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Customer phone supplied: {phone or 'none'}\nMessage: {message}"}]
    calls_log = []
    for _ in range(3):
        result = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages, tools=TOOL_SCHEMAS, tool_choice="auto")
        choice = result.choices[0].message
        if not choice.tool_calls:
            return choice.content or "I can help with products, orders, and returns.", calls_log
        messages.append(choice)
        for call in choice.tool_calls:
            args = json.loads(call.function.arguments)
            value = tools[call.function.name](**args)
            calls_log.append({"tool": call.function.name, "data": value})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(value)})
    return "I need a human representative to review this request.", calls_log

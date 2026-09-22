# Velora Assist

A portfolio-ready, WhatsApp-style commerce support agent for a fictional retail store. It demonstrates a real backend tool layer rather than an LLM that invents answers.

## What the demo can do

- Search a product catalog and recommend items by budget
- Check exact size or variant inventory
- Verify a customer phone number before exposing order data
- Show delivery status and tracking details
- Check return eligibility against the policy
- Create a human-support handoff ticket
- Create owner-approved abandoned-cart reminder drafts
- Record every business tool call in an audit feed

## Agent modes

**Free demo mode:** Runs with deterministic intent routing and seeded fictional data. It needs no API key and is suitable for a portfolio walkthrough.

**LLM mode:** Add `GROQ_API_KEY` to a local `.env` file and connect the existing Groq function-calling adapter. The model chooses tools and writes the answer; it never becomes the source of stock, order, or return facts.

## Run locally

```powershell
cd whatsapp-commerce-ai-agent
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Production path

1. Replace the seeded data functions with WooCommerce or POS adapters.
2. Connect the `/api/chat` webhook adapter to a client-owned WhatsApp Business Platform account.
3. Keep order verification, tool allow-lists, audit logs, and owner approval for any outbound message.
4. Deploy the API and UI separately, with secrets only in the hosting provider environment variables.

This demo does not send actual WhatsApp messages or use real customer data.

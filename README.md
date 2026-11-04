# Probetests — ESCAPE store on a WhatsApp voice agent

Multilingual WhatsApp AI calling agent (Meta models end to end) with a clothing
store on top. Brand: **ESCAPE**. Cash on delivery only.

## How it works

1. Customer browses the storefront (`store/`, Next.js), tries a garment on a live
   camera preview, and orders. Checkout needs name, phone, address and consent
   to a confirmation call.
2. After ordering, the customer opens WhatsApp with a link prefilled with
   `ORDER <id>`. If the sender matches the order phone, the server asks for call
   permission and sends Confirm / Change / Cancel buttons; an AI call confirms
   items, total, address and phone.
3. Support calls: the AI asks for the order phone, reads back the last 4 digits,
   texts a 6-digit OTP to the phone on the order, and only then answers queries.

## Run

Backend (Python 3.12, on the VPS as `wa-backend`):

```bash
cd backend && .venv/bin/pip install -r requirements.txt
.venv/bin/python store.py selfcheck && .venv/bin/python agent.py selfcheck
.venv/bin/python outbound.py selfcheck && .venv/bin/python voice_call.py selfcheck
.venv/bin/python seed_escape.py   # one-time: ESCAPE business + products
systemctl restart wa-backend
```

Storefront:

```bash
cd store && npm install && npm run build && npm start
# NEXT_PUBLIC_API_BASE=https://<api-domain> npm run build   # for production
```

## Built during the event (STORE_BUILD.md)

- Phase 1: `backend/outbound_test.py` — business-initiated call probe (permission,
  SDP offer, MMS line, terminate) with coded rate limits.
- Phase 2: products/orders tables, public order API, `ORDER <id>` link handling,
  confirmation agent + tools, 30-min reminder → `needs_followup`.
- Phase 3: OTP support gate (hashed, 5-min, single-use, 3 attempts, 3 sends/hour,
  same reply for unknown numbers, tools gated on verify).
- Phase 4: `POST /api/public/tryon` — live browser frame in, preview out;
  consent required, 8 MB cap, metadata stripped, in-memory 1h only.
  Photo moderation is a known gap (needs a vision check before public).
- Phase 5: storefront — home, collection, product + fitting room, cart +
  checkout, order confirmation, order status.

Fallbacks in use: order confirmation currently goes over WhatsApp buttons (the
AI confirmation call needs the outbound-audio bridge, built after the call probe
is green on a real phone). `TRYON_ENABLED=false` hides try-on.

## Third-party code and licences

- `pipecat-ai` (BSD-2), `transformers` + `torch` CPU (Apache-2), `aiortc` (BSD),
  `FastAPI`/`uvicorn`/`httpx` (BSD/MIT), `argon2-cffi` (MIT), Next.js/React (MIT),
  Tailwind CSS (MIT).
- Voices: Meta MMS `facebook/mms-tts-*` (CC-BY-NC — demo only, replace to sell).
- Models: Muse Spark 1.3 (LLM + tools), Muse Voice Transcribe 1.0 (STT),
  Muse Image 1.0 (try-on edits) — Meta Model API.
- Product photos: Unsplash free-licence library, files in
  `store/public/products/`. Try-on previews are generated images, deleted within
  an hour, never committed.

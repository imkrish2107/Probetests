# Agent dashboard — AI shops for you, on WhatsApp

One logged-in dashboard where agents shop for the user. Two flows on one
shared engine: **shopping** (drop a photo, get verified listings, ask the
seller, place an order, track it) and **construction** (floor plan → room
check → BOQ → concept house image → approval → vendor search → calls →
compare). Payment stays user↔seller, cash on delivery; the app never takes or
stores card, bank or UPI details, and never logs into seller sites.

## How it works

**Shopping.** Photo in → Spotter (colour, garment, pattern, fabric) → Finder
searches (≤3, ≤12 candidates) → Checker verifies price/stock in the page, JSON-LD
or a confirmed quote → Ranker picks best verified price first. Ask-the-seller
shows the exact message before Send. Place order is a confirmation screen
(item, seller, price, delivery, name/address from Setup); the seller gets the
address only on Confirm. Picker picks cheapest/fastest/arrive-by delivery,
Buyer rejects a stale price or seller, Tracker chases confirmed orders every
6 hours and needs eyes after 3 unanswered reminders.

**Construction.** Plan in → Plan Reader extracts rooms (user corrects, per-room
accuracy shown) → Quantity Surveyor builds a BOQ in plain code (whole-building
per-sqft rates +7.5% wastage, tiles +10%, paint by perimeter) → House Artist
(Muse Image, ≤5/hunt, labelled concept-only) → user Approves BOQ + image by
hash (any edit clears approval, vendor search/calls refuse without it) →
vendor search (≤10 items, 20 searches, 8 vendors/item, city in the query) →
Quote Caller → Compare (Best/Cheapest per item, running total, no house total
until all quoted).

**Safety.** Untrusted page/seller text never picks recipients or prices — only
code acts, from DB values, after a logged-in click. Only opted-in sellers are
messaged (STOP flips opt-in off instantly); everyone else gets an invite link
from the user's own WhatsApp. Pages refuse to run before robots/captcha/login,
fetch politely (10 s, 2 MB, ≤3 redirects), and never save others' images.

## Run

Backend (Python 3.12, git-ignored `.venv`):

```bash
cd backend && .venv/bin/pip install -r requirements.txt
.venv/bin/python purchases.py selfcheck && .venv/bin/python sellers.py selfcheck
```

Dashboard (Next.js, ledger styling, no tokens in HTML):

```bash
cd dashboard && npm install && npm run build && npm start
```

Keys come only from `backend/.env` (never committed, never printed — checks
print only which names are empty).

## Deploy (VPS, as root on hal-server; `sudo` is broken there)

```bash
cd /home/wa/Probetests && git pull
cd backend && .venv/bin/python purchases.py selfcheck && .venv/bin/python sellers.py selfcheck
systemctl restart wa-backend && systemctl is-active wa-backend
```

## Status

- Live in code: hunts, BOQ, house image + approval gate, vendor search,
  purchases/Picker/Buyer/Tracker, full dashboard (390 px → 1440 px).
- Fallbacks in use: vendors get `quote_request` on WhatsApp and the Compare
  table links `tel:`/invite instead of AI calls — `backend/quote_call.py` stays
  out of the repo until the phone test passes.
- Not yet proven on a real phone: the call probe (Part G), one shopping hunt,
  one read-plan with per-room accuracy, one house image, one 2-item vendor
  search. Nothing above is marked passed until real output is seen.

## Built during the event (AGENT_DASH_BUILD.md, CONSTRUCTION_BUILD.md)

Parts D–G: BOQ in plain code with gates and CSV; House Artist + approval hash;
vendor search per BOQ item; outbound call plumbing with per-vendor limits.
Part J: dashboard for both flows. Part I: orders end to end.

## Third-party code and licences

FastAPI/uvicorn/httpx (BSD/MIT), Next.js/React (MIT). Models, all Meta:
`muse-spark-1.3`, `sam-3.1`, `muse-voice-transcribe-1.0`,
`facebook/mms-tts-*` (CC-BY-NC voices — demo only), `muse-image-1.0`.
No other search or AI APIs.

# [BRAND] store build: 2-hour instruction file

You are building this now, in one run, in this repo. Work through the phases in order and do not stop for approval unless a section says **STOP**.

## Owner fills in before starting

- Brand name: `[BRAND]`
- Test WhatsApp number, with country code: `[TEST_NUMBER]`
- At least 6 product photos with rights to use them, in `store/public/products/`
- A licensed or own person photo for the try-on test: `backend/tryon_test/person.jpg` (git-ignored)

If `[BRAND]` or `[TEST_NUMBER]` is still a placeholder, or the photos are missing, **STOP** and ask for them.

## Rules for the whole run

- Smallest change that works. No extra features, abstractions or config layers.
- Read only the files a phase touches. Never read `.venv`, `node_modules`, model weights or whole logs.
- Keys come only from `backend/.env`. Never print, log or commit their values. To check keys, print only which names are empty.
- Never commit `.env*`, databases, backups, customer photos or real customer data. The repo becomes public. Add ignore rules before creating such files.
- Keep existing booking and call features working. Reuse the existing STT, TTS, `call_lang` and tool-calling code.
- Meta models only in the product: `muse-spark-1.3`, `muse-voice-transcribe-1.0`, `facebook/mms-tts-<lang>`, `muse-image-1.0`.
- Muse limits on calls: 1-2 short spoken sentences, last 8 turns only, and save tokens and audio seconds per call.
- Catch errors at the edges and log them. One bad call or API error must never crash the server. Webhooks return 200 fast and do slow work in a background task.
- Plan each phase in at most 5 lines, then start it without waiting.
- End each phase by running its check, printing the result, then committing with a short message. If a check fails, fix it within the phase's time box. Otherwise take the phase's fallback.
- Don't claim something works unless you ran it. Say clearly what only a real phone can prove.

## Time plan

| Phase | Work | Minutes | Ends by |
|---|---|---:|---:|
| 1 | Outbound call test | 20 | 0:20 |
| 2 | Orders and confirmation call | 20 | 0:40 |
| 3 | Support line with OTP | 15 | 0:55 |
| 4 | Virtual try-on | 15 | 1:10 |
| 5 | Storefront | 35 | 1:45 |
| 6 | End-to-end check and README | 15 | 2:00 |

If behind schedule, cut in this order: extra languages on the store pages, then try-on, then the unanswered-call retry. Never cut the storefront, confirmation flow, OTP gate or the secret scan.

## What we are building

[BRAND] is a clothing store on the existing WhatsApp voice agent. Cash on delivery only, with no payment fields.

1. Customers browse, try clothes on a photo of themselves, and order.
2. After ordering, the customer opens WhatsApp with a link prefilled with `ORDER <id>`. If the sender matches the order phone, send a call permission request. Once approved, the AI calls.
3. The call says it is an AI assistant, checks it is speaking to the customer, confirms items and total, then re-checks the delivery address and phone. It records confirmed, change requested or cancelled.
4. Support calls: ask for the order phone number, read back the last 4 digits, send an OTP to WhatsApp, verify it, then ask for the query.

## Phase 1: Outbound call test (20 min)

Read:
- https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/business-initiated-calls
- https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/user-call-permissions

Pipecat's WhatsApp client only answers incoming calls. Check the installed Pipecat and aiortc code, then build the smallest script, `backend/outbound_test.py`, that:
1. Sends the interactive `call_permission_request` to `[TEST_NUMBER]` inside the open service window.
2. Creates an SDP offer and sends `action: "connect"` to `POST /<PHONE_NUMBER_ID>/calls`.
3. Applies the SDP answer from the Call Connect webhook, where `direction` is `BUSINESS_INITIATED`.
4. Plays one MMS line, then sends `action: "terminate"`.

Handle error 138006 and every webhook failure. Enforce limits in code: 1 permission request per 24 hours, 2 per 7 days, and stop before 4 unanswered calls in a row.

**Check:** print the exact command for the owner, then **STOP** until the owner reports the phone rang and the line played.

**Fallback at 0:20:** if outbound still fails, log the exact error and report it. Replace the call with a WhatsApp confirmation message with Confirm, Change and Cancel buttons, plus a Call support button that reaches the Phase 3 agent. Keep Phase 2's order statuses the same. Tell the owner the fallback is in use.

## Phase 2: Orders and confirmation call (20 min)

Build:
- SQLite tables and API for products, orders and order items, with prices and totals computed on the server.
- Order statuses: `pending_call`, `confirmed`, `change_requested`, `cancelled`, `shipped`, `delivered`, `needs_followup`.
- Link an incoming `ORDER <id>` WhatsApp message to its order only if the sender matches the order phone. Then request permission and start the outbound call.
- A confirmation-call agent with its own short prompt and tools: `get_order_for_call`, `confirm_order`, `request_change`, `cancel_order`, `end_call`. Tools use the order from call state and never accept another order ID.
- If unanswered, retry once after 30 minutes, then send a WhatsApp message and set `needs_followup`.
- Save the transcript, outcome, tokens and audio seconds.

**Check:** offline selfchecks pass for status changes and wrong-phone rejection.

## Phase 3: Support line with OTP (15 min)

Add a support-call agent for incoming store calls:
- Say it is an AI assistant, ask for the order phone number, and read back the last 4 digits.
- Send a 6-digit OTP only to the phone stored on the order, never to a different number the caller gives.
- Say the same thing whether or not the number exists: "If that number has an order, I've sent a code."
- Store OTPs hashed. They expire in 5 minutes, are single use, and allow 3 attempts and 3 sends per hour. Never log them or put them in prompts.
- Verification is decided in code. Before it passes, order tools return `not_verified` and the LLM receives no order data.
- After it passes, ask for the query. Tools work only on orders for that phone: `get_order_status`, `request_address_change` (before shipping only), `cancel_order` (before shipping only), `create_return_request`, `request_human_callback`. Refunds always become a human task.

Use a WhatsApp authentication template for the OTP. If it isn't approved, use a free-form message only when the service window is open. Otherwise explain the failure and create a callback task.

**Check:** selfchecks pass for expiry, attempt limits, unknown numbers and the data gate.

## Phase 4: Virtual try-on (15 min)

Read:
- https://dev.meta.ai/docs/api-reference/images/edit-image
- https://dev.meta.ai/docs/image-generation

First test `muse-image-1.0` on `/v1/images/edits` with `backend/tryon_test/person.jpg` and one product photo. Save the result in `backend/tryon_test/` and show the path. If it clearly changes the face, body or garment, adjust the prompt once. If it's still bad, use the fallback.

Then build `POST /api/public/tryon`:
- Requires a consent flag. Accepts only JPEG, PNG or WebP up to 8 MB. Strip metadata and rate-limit by IP.
- Prompt: keep the person's face, body shape, skin tone, pose and background unchanged; change only the clothing to match the garment's colour, pattern and cut.
- Reject photos of minors, nudity or anything other than one clearly visible person. Never sexualise the image.
- Don't save customer photos in SQLite or git. Hold results in memory for at most 1 hour.
- Log cost per try-on. Return clear errors for poor photos and API failures.

**Check:** one real request returns an image, and a request without consent returns an error.

**Fallback at 1:10:** hide the try-on button behind `TRYON_ENABLED=false`, report why, and continue. Never fake a try-on result.

## Phase 5: Storefront (35 min)

Build a new Next.js App Router + TypeScript + Tailwind app in `store/`. Keep `BACKEND_API_KEY` on the server only.

Pages: home, collection, product with try-on, cart, checkout, order confirmation, order status.

### Design: an independent fashion label's printed lookbook, not a SaaS template

- Fonts: Newsreader for headings and Familjen Grotesk for interface text.
- Colours: warm paper `#F4F0E8`, ink `#1C1A17`, oxblood `#6E1F1B` used sparingly.
- Sharp corners or 2px at most, hairline rules instead of shadows, and a strict 12-column grid with deliberate asymmetry.
- Real product photos lead every page, with large images and generous space. Use only `store/public/products/`. Never generate or fake product photos.
- Copy is short, specific and human: fabric, fit, care and what the model wears. Include a real size guide, not marketing filler.
- Motion only for image fades and cart feedback, under 200 ms. Respect reduced motion.

**Never use:** gradients, glass effects, purple or blue accents, emoji, sparkle icons, robot imagery, floating blobs, three-feature card rows, generic centred heroes with two buttons, rounded card grids, fake reviews or stats, "AI-powered", "seamless", "elevate" or "revolutionary".

### Flows

- Try-on feels like a fitting room: a calm photo guide, clear consent, "Your photo is used only for this preview and deleted within an hour", real progress and failure states, and a before/after view. Label results "Preview. Fit and colour may vary."
- Checkout needs name, phone, address and clear call consent, with cash on delivery only.
- Order confirmation has one main action: Confirm on WhatsApp.
- Build mobile first at 390 px, then 1440 px. Use keyboard-accessible, labelled controls, WCAG AA contrast, and real loading, empty and error states.

**Check:** `npm run build` passes. Screenshot every page at 390 px and 1440 px, list anything that looks templated, fix it, and save the screenshots outside git.

## Phase 6: End-to-end check and README (15 min)

Run the full flow without adding features:

try-on -> order -> WhatsApp link -> permission -> AI call -> confirmed status -> incoming support call -> OTP -> status query

Also test wrong OTP, wrong phone, unanswered call, cancelled order, and English, Hindi and Tamil calls.

Deploy on the VPS as root. `sudo` is broken there, so don't use it. Use the venv Python:

```bash
cd /home/wa/Probetests && git pull && cd backend && .venv/bin/python voice_tts.py selfcheck && .venv/bin/python agent.py selfcheck && .venv/bin/python voice_call.py selfcheck && systemctl restart wa-backend && systemctl is-active wa-backend
```

Before any push, scan the working tree and full git history for secrets, customer photos and databases. **STOP** and report if anything is found.

Update the README: what the project is, how to run it, what was built during the event, third-party code and licences, and image sources.

**Final report:** a PASS/FAIL checklist with evidence for each item, separating what you ran from what the owner must test on a phone. List every fallback used.

Then tell the owner what is left for submission by the deadline, Wed Nov 4, 9:00 PM ET: public repo, working 3-minute demo video link, and every team member added.

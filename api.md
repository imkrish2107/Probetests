# API (every endpoint, one place)

The single list of endpoints. [backend.md](backend.md) builds them, [frontend.md](frontend.md) calls them. If an endpoint isn't here, it doesn't exist.

## Who can call what
| Caller | How it proves who it is | Can reach |
| --- | --- | --- |
| Meta (WhatsApp) | `X-Hub-Signature-256` (HMAC with `WHATSAPP_APP_SECRET`) | `/webhook` |
| Next.js server on Netlify | `X-API-Key: BACKEND_API_KEY` | `/api/auth/signup`, `/api/auth/login`, `/api/public/*` |
| Next.js server for a logged-in user | `X-API-Key` **and** `Authorization: Bearer <session token>` | Everything else under `/api` |
| Anyone | nothing | `/health` |

The browser never calls FastAPI: it talks to Next.js, and Next.js calls FastAPI from its server with the key and the user's session token (kept in an httpOnly cookie).

- **Roles:** `owner` (everything) and `staff` (everything except `PUT /api/business`). Each user sees only their own business's data.
- **Errors:** `{"error": {"code": "not_found", "message": "..."}}` with 400, 401, 403, 404, 409, 422 or 429.
- **Lists** return `{"items": [...], "next_before": <id or null>}`; pass `?before=<id>&limit=50` for the next page.
- **Contacts** are identified by WhatsApp user ID; `phone` can be empty for callers who use a WhatsApp username.
- **Times** are ISO 8601 in the business's time zone; money in US dollars with 6 decimals.

## Backend endpoints (FastAPI, `https://api.<domain>`)

### Health and webhook
| Method | Route | Body / query | Response | Notes |
| --- | --- | --- | --- | --- |
| GET | `/health` | | `{"ok": true}` | For uptime checks; no data |
| GET | `/webhook` | `hub.mode`, `hub.verify_token`, `hub.challenge` | the challenge, plain text | Meta's "Verify and save" |
| POST | `/webhook` | Meta event JSON | `200` at once | Signature checked; work happens in the background. Events below |

`POST /webhook` events (routed to a business by `metadata.phone_number_id`; unknown numbers are logged and ignored):
| `field` / event | What we do |
| --- | --- |
| `calls` → `connect`, `USER_INITIATED` | Answer: start the call bot, `pre_accept` + `accept` within 30 s. Save `deeplink_payload` as the call's source |
| `calls` → `connect`, `BUSINESS_INITIATED` | Our AI callback was picked up: hand the SDP answer to the call bot (stretch) |
| `calls` → `terminate` | Save duration and status, run the post-call automation |
| `calls` → statuses `RINGING` / `ACCEPTED` / `REJECTED` | Update our outgoing callback (stretch) |
| `messages` → statuses `sent` / `delivered` / `read` / `failed` | Update the matching row in `messages` |
| `messages` → incoming message from a customer | Set the contact's `last_inbound_at` (opens the 24-hour chat window); one automatic Call Now reply per contact per day; shown on the contact page |

### Auth
| Method | Route | Body | Response | Notes |
| --- | --- | --- | --- | --- |
| POST | `/api/auth/signup` | `{business_name, name, email, password, signup_code?}` | `201 {token, user, business}` | Creates the business and its owner. Password at least 8 characters. `signup_code` required when `SIGNUP_CODE` is set. 409 if the email exists |
| POST | `/api/auth/login` | `{email, password}` | `{token, user, business}` | 401 on a wrong email or password (same message for both). 5 tries per minute per email, then 429 |
| POST | `/api/auth/logout` | | `204` | Deletes the session |
| GET | `/api/auth/me` | | `{user: {id, name, email, role}, business: {id, name, slug}}` | Used by the dashboard layout |

### Dashboard data
| Method | Route | Body / query | Response |
| --- | --- | --- | --- |
| GET | `/api/stats` | `?date=` (default today) | `{calls, bookings, open_tasks, urgent_tasks, cost_usd}` |
| GET | `/api/calls` | `?before=&limit=` | items: `{id, contact: {id, name, phone_masked}, direction, source, language, started_at, duration_s, outcome, cost_usd}` |
| GET | `/api/calls/{id}` | | the call + `summary`, `transcript: [{role, text, language, at}]`, `bookings`, `tasks`, `messages`, `crm_changes`, `tokens_in`, `tokens_out`, `audio_seconds`, `cost_usd` |
| GET | `/api/bookings` | `?date=` (default today) | `{items: [{id, contact_id, name, party_size, slot, note, status, reminder_sent_at}]}` |
| PATCH | `/api/bookings/{id}` | `{slot}` or `{status: "cancelled"}` | the booking; sends `booking_changed` to the customer |
| GET | `/api/tasks` | `?status=open\|done&before=&limit=` | items: `{id, type, details, urgency, status, contact, call_id, created_at}`, urgent first |
| PATCH | `/api/tasks/{id}` | `{status: "done", note}` | the task; sends `task_done` with the note to the customer |
| GET | `/api/contacts` | `?q=&before=&limit=` | items: `{id, name, phone_masked, language, stage, tags, last_call_at, calls_count}` |
| GET | `/api/contacts/{id}` | | the contact + `notes`, `phone`, `last_inbound_at`, `call_permission`, `calls`, `bookings`, `tasks`, `messages` |
| PATCH | `/api/contacts/{id}` | `{name?, stage?, tags?, notes?}` | the contact |
| GET | `/api/business` | | `{name, slug, wa_phone_number_id, wa_display_number, call_link, timezone, hours, slot_minutes, seats_per_slot, menu, prices, faqs, languages, owner_whatsapp, crm_webhook_url}` |
| PUT | `/api/business` | same fields except `slug` and `call_link` | the business (owner only) |
| GET | `/api/templates` | | `{items: [{name, language, status}]}`, read from Meta, cached 5 minutes |

### Team (stretch: only the owner exists until this is built)
| Method | Route | Body | Response | Notes |
| --- | --- | --- | --- | --- |
| GET | `/api/users` | | `{items: [{id, name, email, role, last_login_at}]}` | Owner only |
| POST | `/api/users` | `{name, email, password}` | `201` the user | Owner creates a `staff` login; 409 if the email exists |
| DELETE | `/api/users/{id}` | | `204` | Owner only; deletes the user's sessions too; can't delete yourself |

### Calling buttons
| Method | Route | Body | Response | Notes |
| --- | --- | --- | --- | --- |
| POST | `/api/contacts/{id}/call-button` | `{message?}` | `{message_id, kind: "interactive" \| "template"}` | Sends the customer a **Call Now** button. Inside the 24-hour window: interactive `voice_call` message; otherwise the `call_us` template |
| POST | `/api/contacts/{id}/callback` | `{purpose}` | `202 {call_id}` | **Stretch.** The AI calls the customer. 409 `no_permission` if they never gave call permission (the dashboard then offers the call button instead) |
| GET | `/api/live` | | `{items: [{call_id, contact, started_at, language}]}` | **Stretch.** Calls in progress |

### Public (no login, still needs `X-API-Key`)
| Method | Route | Response | Notes |
| --- | --- | --- | --- |
| GET | `/api/public/businesses/{slug}` | `{name, call_link, hours}` | For the public "Call us" page |

## Data shapes
Fields that aren't plain text or numbers:
| Field | Shape | Example |
| --- | --- | --- |
| `timezone` | IANA name | `"Asia/Kolkata"` |
| `hours` | Per weekday, list of open-close pairs (24 h); empty list = closed | `{"mon": [["09:00","22:00"]], "tue": [], ...}` |
| `menu` | List of items | `[{"name": "Masala dosa", "price": 120, "allergens": ["gluten"], "veg": true}]` |
| `prices` | Free text for prices not on the menu | `"Catering from ₹450 per person"` |
| `faqs` | List of question-answer pairs | `[{"q": "Parking?", "a": "Free, behind the cafe"}]` |
| `languages` | Ordered list; first one is used for the greeting | `["Hindi", "English", "Tamil"]` |
| `slot` (bookings) | ISO date-time in the business time zone | `"2026-10-31T20:00:00+05:30"` |
| `outcome` (calls) | `booked`, `task`, `answered`, `busy`, `missed` | |
| `stage` (contacts) | `new`, `lead`, `booked`, `customer` | |
| task `type` | `catering_quote`, `pickup_order`, `complaint`, `refund`, `callback`, `message`, `other` | |
| message `kind` | `followup`, `reminder`, `booking_changed`, `task_done`, `owner_alert`, `call_button`, `auto_reply` | |
| message `status` | `queued`, `sent`, `delivered`, `read`, `failed` | |

`PUT /api/business` returns 422 with the field name if a shape is wrong (bad time zone, overlapping hours, unknown language).

## CRM webhook (what the business's own system receives)
After each call, if the business set `crm_webhook_url`, the backend sends `POST <crm_webhook_url>` with `Content-Type: application/json`:
```json
{"event": "call.completed", "business": "Your Cafe",
 "contact": {"name": "Priya", "phone": "+9198xxxxx210", "language": "hi", "stage": "booked", "tags": ["party"]},
 "call": {"id": 42, "started_at": "2026-10-31T18:02:11+05:30", "duration_s": 154, "outcome": "booked",
          "summary": "Booked a table for 4 on Saturday 8 PM; asked for a 40-person party quote."},
 "bookings": [{"slot": "2026-11-01T20:00:00+05:30", "party_size": 4}],
 "tasks": [{"type": "catering_quote", "details": "40 people, Sunday", "urgency": "normal"}]}
```
Any 2xx counts as delivered; otherwise one retry after 1 minute, then marked failed on the call.

## Agent tools (not HTTP: functions Muse Spark calls during a call)
`check_slots`, `book_table`, `reschedule_booking`, `cancel_booking`, `take_message`, `request_callback`, `create_task`, `end_call`. Arguments and behaviour: [backend.md](backend.md) → Tasks.

## Not an endpoint on purpose
- **Creating templates:** `python templates.py create` (run once per language set); the dashboard only reads status with `GET /api/templates`.
- **Turning calling on:** a one-time `POST /{phone_number_id}/settings` from `whatsapp.py`.
- **Booking or task created by hand on the dashboard:** not planned; bookings and tasks come from calls.

## Outside APIs the backend calls
| Service | Method + endpoint | Used for |
| --- | --- | --- |
| Muse Spark | `POST https://api.meta.ai/v1/chat/completions` | Live replies (streaming, tools); post-call JSON |
| Muse Transcribe | `wss://api.meta.ai/v1/asr/realtime` | Live speech-to-text, end-of-turn detection |
| WhatsApp | `POST /{phone_number_id}/calls` `pre_accept`, `accept`, `terminate` | Answering and ending calls |
| WhatsApp | `POST /{phone_number_id}/calls` `connect` | AI callback (stretch) |
| WhatsApp | `POST /{phone_number_id}/messages` | Templates, interactive `voice_call` button, owner alerts |
| WhatsApp | `GET` / `POST /{phone_number_id}/settings` | Turn calling and callback permission on |
| WhatsApp | `GET` / `POST /{waba_id}/message_templates` | Create templates, read approval status |
| Business's CRM (optional) | `POST <crm_webhook_url>` | Contact + call JSON after each call |

The call link needs no API: `https://wa.me/call/<wa_display_number>?biz_payload=<source>` (`website`, `qr`, `followup`). The source comes back in the `connect` webhook as `deeplink_payload`. It doesn't work on WhatsApp desktop.

## Dashboard routes (Next.js on Netlify)
| Route | Login | Calls these endpoints |
| --- | --- | --- |
| `/login` | public | `POST /api/auth/login` (server action, sets the cookie) |
| `/signup` | public | `POST /api/auth/signup` (server action, sets the cookie) |
| `/c/[slug]` | public | `GET /api/public/businesses/{slug}` |
| `/` Calls | yes | `GET /api/stats`, `GET /api/calls` |
| `/calls/[id]` | yes | `GET /api/calls/{id}`, `POST /api/contacts/{id}/call-button` |
| `/bookings` | yes | `GET /api/bookings`, `PATCH /api/bookings/{id}` |
| `/tasks` | yes | `GET /api/tasks`, `PATCH /api/tasks/{id}`, `POST /api/contacts/{id}/call-button` |
| `/contacts` | yes | `GET /api/contacts` |
| `/contacts/[id]` | yes | `GET /api/contacts/{id}`, `PATCH /api/contacts/{id}`, `POST /api/contacts/{id}/call-button`, `POST /api/contacts/{id}/callback` (stretch) |
| `/setup` | yes (owner edits) | `GET` / `PUT /api/business`, `GET /api/templates`; team section (stretch): `GET` / `POST /api/users`, `DELETE /api/users/{id}` |
| every page | yes | `GET /api/auth/me` (layout), `GET /api/stats` (open-task count in the top bar), `POST /api/auth/logout` (logout button) |

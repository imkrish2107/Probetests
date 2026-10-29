# Backend

One Python 3.12 app in `backend/`: FastAPI takes WhatsApp's webhooks and serves the API for the Next.js dashboard; Pipecat runs each live call. It runs on a Bluehost VPS (2 vCPU, 4 GB RAM) together with the SQLite database; the dashboard is on Netlify. Every endpoint: [api.md](api.md). Overall plan: [planner.md](planner.md).

## Files
| File | Job | Step |
| --- | --- | --- |
| `models.py` | `reply()` for every Muse chat model, with tokens and cost | done |
| `muse_check.py` | Sends "hello" to a model and prints reply, tokens, cost | 1 |
| `whatsapp.py` | Graph API helpers: call actions, templates, interactive messages, settings | 2 |
| `main.py` | `/health`, `/webhook`, all `/api` routes ([api.md](api.md)) | 2, 8 |
| `call_bot.py` | Pipecat pipeline for one call | 3, 5 |
| `muse_stt.py` | Pipecat STT service for Muse Voice Transcribe realtime | 4 |
| `mms_tts.py` | Pipecat TTS service for Meta MMS, one voice per language | 3, 5 |
| `agent.py` | System prompt from the business settings, language rule, tools | 6 |
| `automation.py` | After the call: summary, CRM, follow-up, owner alert; 5-minute scheduler | 7 |
| `templates.py` | Creates the WhatsApp templates and shows their approval status | 3 (create), 7 |
| `auth.py` | Signup, login, sessions, password hashing, role checks | 8 |
| `db.py` | SQLite schema and helpers | 2 onwards |

## Voice: what is Meta AI and what isn't
| Job | What we use | Why |
| --- | --- | --- |
| Hearing (STT) | **Muse Voice Transcribe** `muse-voice-transcribe-1.0`, realtime | Meta Model API. 25 languages with code-switching, $0.18 per audio hour. |
| Thinking (LLM) | **Muse Spark** `muse-spark-1.3` | Meta Model API, OpenAI-compatible, tool calling. |
| Speaking (TTS) | **Meta MMS** `facebook/mms-tts-<lang>`, on our VPS | Meta's Model API has **no text-to-speech**, so we run Meta's open MMS voices ourselves. Free; licence CC-BY-NC (fine for the hackathon, replace before selling). |

### STT: `muse_stt.py`
- One WebSocket per call to `wss://api.meta.ai/v1/asr/realtime`.
- First frame within 10 s (the key goes in the JSON, not the HTTP header):
  ```json
  {"authorization": {"accessToken": "Bearer <MODEL_API_KEY>"},
   "model": "muse-voice-transcribe-1.0", "audioEncoding": "PCM_16KHZ",
   "mode": "ENDPOINTING", "partialMode": "CUMULATIVE",
   "languageBias": ["English", "Hindi", "Tamil"],
   "keywords": ["<business name>", "<menu items>"]}
  ```
  Wait for the `{"sessionId": ...}` reply before sending audio.
- Audio: 16-bit mono PCM at 16 kHz in binary frames, paced at real time (never more than 5 s ahead).
- **End of turn:** `ENDPOINTING` mode lets Muse detect when the caller stops (`speechStart` → `transcript` partials → `speechEnd` → `speechComplete` with the final text, keyed by `turnId`). Our own volume check stays only as a fallback.
- **Barge-in:** a `speechStart` while the agent is talking stops the agent's audio (Pipecat interruption).
- `languageBias` comes from the business's languages; it steers but doesn't force, so callers can switch.
- One session per call (max 60 min). Send `{"type":"endStream"}` at hang-up.

### TTS: `mms_tts.py`
- `transformers` `VitsModel` + `AutoTokenizer` for `facebook/mms-tts-<code>`; 16 kHz output, Pipecat resamples it for the call.
- Load the business's languages once at startup (about 150 MB each), keep them in memory.
- Speak sentence by sentence as the LLM streams; the first sentence is 2-3 words ("Sure, one moment.").
- Native script in, no romanising step (checked for eng, hin, tam, tel, kan, ben, mar).
- `torch.set_num_threads(2)` and `torch.inference_mode()`. If Day 5 shows the voice is the slow part: export to ONNX and run with `onnxruntime` (faster on CPU, much less RAM).

### Latency budget (caller stops talking → hears the reply)
| Part | Target | How |
| --- | --- | --- |
| End of turn detected | ~0.3-0.7 s | Muse Transcribe ENDPOINTING |
| Muse Spark first sentence | ~0.4-0.8 s | Streaming, `reasoning_effort` minimal, 120-token cap, short fixed prompt (cached) |
| MMS first sentence | ~0.1-0.3 s | Sentence-by-sentence, voices preloaded |
| Network | ~0.1-0.3 s | VPS close to callers; audio goes straight to the VPS |
| **Total** | **under 2 s** | Estimates: log each part per turn from step 5 and fix the biggest |

### Languages we can do end to end
| Language | Muse Transcribe | MMS voice | Template code |
| --- | --- | --- | --- |
| English | ✅ | `mms-tts-eng` | `en` |
| Hindi | ✅ | `mms-tts-hin` | `hi` |
| Tamil | ✅ | `mms-tts-tam` | `ta` |
| Telugu | ✅ | `mms-tts-tel` | `te` |
| Kannada | ✅ | `mms-tts-kan` | `kn` |
| Bengali | ✅ | `mms-tts-ben` | `bn` |
| Marathi | ✅ | `mms-tts-mar` | `mr` |

Malayalam, Gujarati and Punjabi have MMS voices but aren't on Muse Transcribe's list. Demo: English + Hindi + Tamil.

## LLM layer
- **Live call:** Pipecat's OpenAI LLM service pointed at `base_url="https://api.meta.ai/v1"`, model from `LLM_MODEL`, `max_completion_tokens` 120, `reasoning_effort` `"minimal"`, streaming on.
- **Everything else** (post-call JSON, tests): `models.reply()`.
- **Context:** system prompt + the last 8 turns. The prompt is built once per call from the business settings and stays byte-for-byte the same (cache), under 400 words.
- **Language rule** in the prompt: "Reply in the language the caller last spoke, in its native script. Start every reply with a tag like `[hi]`." The tag picks the MMS voice and is stripped before speaking; if it's missing, the script of the text decides. The call's language is saved for the follow-up and the CRM.

## Tasks: what happens when a caller asks for something
Demo business: **Your Cafe**. Every request ends in one of three places, so the caller is never left without an answer.

| Kind | Cafe examples | How it's automated |
| --- | --- | --- |
| **1. Done during the call** | Book, move or cancel a table; "Are you open Sunday?"; menu, prices, location | Muse Spark calls a tool, the backend runs it at once, the agent confirms out loud |
| **2. Done after the call** | Booking confirmation, reminder 3 hours before | `automation.py` sends the template; the scheduler sends reminders |
| **3. Needs a person** | Catering or party quote, pickup order, complaint, refund, special requests | Agent says "I've passed this to the team, you'll get a WhatsApp update", creates a task, owner gets an alert. Staff mark it done → customer gets `task_done` |

**Never guessed:** allergy and ingredient questions are answered only from the menu in the business settings; anything not listed becomes a task. Complaints and refunds are always urgent tasks.

### Tools (Muse Spark tool calling)
| Tool | Args | Does |
| --- | --- | --- |
| `check_slots` | `date, party_size` | Free times that day, from opening hours, slot length and seats per slot |
| `book_table` | `name, party_size, slot, note` | Saves a booking; the agent reads it back before ending |
| `reschedule_booking` | `new_slot` | Finds the caller's next booking by phone number and moves it |
| `cancel_booking` | `reason` | Finds the caller's next booking and cancels it |
| `take_message` | `name, message` | Creates a task of type `message` |
| `request_callback` | `reason` | Urgent task of type `callback` when the caller wants a person |
| `create_task` | `type, details, urgency` | `catering_quote`, `pickup_order`, `complaint`, `refund`, `other`; urgency `normal` or `urgent` |
| `end_call` | `reason` | Says goodbye, then `terminate` |

### Scheduler (inside the backend process, every 5 minutes)
- Sends `booking_reminder` 3 hours before each booking (once; `reminder_sent_at` set).
- Re-alerts the owner about `urgent` tasks still open after 30 minutes.

### Example call
Caller (Hindi mixed with English): *"Saturday raat 8 baje 4 logon ke liye table chahiye, aur Sunday ko 40 logon ki party ka quote bhi chahiye."*
| When | What happens |
| --- | --- |
| During the call | `check_slots(Sat, 4)` → 8:00 free → `book_table` → read back in Hindi. Party request → `create_task(catering_quote, "40 people, Sunday", normal)` |
| Seconds after hang-up | `booking_confirmed` in Hindi; contact updated; owner alert "New booking + catering quote request"; task on the dashboard |
| Saturday 5 PM | `booking_reminder` |
| Staff mark the task done with a note | `task_done` with that note |

## A call, start to finish
1. **connect** webhook. `main.py` checks the signature, finds the business by `phone_number_id`, returns 200, starts `call_bot` in the background. Over `MAX_CALLS`: the bot answers, says the lines are busy and takes a message.
2. Pipecat builds the SDP answer; `whatsapp.py` sends `pre_accept`, then `accept` with the **same** answer, within 30 s. No audio before `accept` returns 200.
3. Greeting in the business's first language that says it's the business's AI assistant ("Hi, this is Your Cafe's AI assistant..."), then the loop: caller audio → Muse Transcribe → Muse Spark (tools) → MMS → caller.
4. Each turn's text, tokens and audio seconds are saved as they happen.
5. `end_call` (we send `terminate`) or the caller hangs up → **terminate** webhook.
6. `automation.py` runs (next section).
7. Message status webhooks update the `messages` rows.

## Every way a customer's call can go
| Situation | What happens |
| --- | --- |
| **New caller** | Contact created from the `connect` webhook; agent greets as the cafe's AI assistant |
| **Returning caller** | Contact found by WhatsApp user ID; the first turn gets their name and next booking ("Hi Priya, calling about Saturday's table?") |
| **Caller uses a WhatsApp username** (no phone number in the webhook) | Contacts are keyed by `from_user_id` (WhatsApp's business-scoped user ID), phone stored when present. Replies use the user ID |
| **Asks for a person** ("let me talk to someone") | No live transfer on WhatsApp calls. Agent creates an urgent `callback` task and says the team will call back; owner alert includes the call link so they can call from their own WhatsApp |
| **Outside opening hours** | Calls are still answered (we don't set WhatsApp `call_hours`). Agent says the cafe is closed, takes bookings for open times and messages |
| **All lines busy** (over `MAX_CALLS`) | Answered, "all our lines are busy", message taken, follow-up sent |
| **Two callers want the last table** | `book_table` checks seats and saves in one SQLite transaction; the second caller is offered the next free slot |
| **Hangs up mid-booking** | Nothing half-saved; `call_thanks` follow-up with the call link so they can call back |
| **Silence or noise, no speech for 10 s** | "Are you still there?"; 10 s more, then a polite goodbye and `terminate` |
| **Language we don't speak** | Agent replies in English and offers to take a message |
| **Says a relative date** ("kal", "Saturday raat 8 baje") | Today's date, weekday and time in the business time zone go in a short system message after the fixed prompt (so the cached prefix stays the same); tools only take ISO dates |
| **Texts instead of calling** | Incoming message → `last_inbound_at` set; one automatic interactive reply with a **Call Now** button ("Call us, our assistant answers 24/7"), at most once a day per contact; shown on the contact page |
| **Calls from WhatsApp desktop or Web** | WhatsApp doesn't allow it; nothing reaches us |
| **Our server is down** | The caller sees "Not answered". systemd restarts the backend within seconds; a free uptime monitor pings `/health` every 5 minutes and emails you; no follow-up can be sent for missed calls we never saw |

## After the call: `automation.py`
One Muse Spark call (`max_tokens` 400) reads the transcript and returns JSON:
```json
{"summary": "...", "outcome": "booked|task|answered", "language": "hi",
 "customer_name": "Priya", "stage": "booked", "tags": ["party"],
 "followup": {"template": "booking_confirmed", "params": ["Priya", "Your Cafe", "Sat 8 PM"]},
 "owner_alert": "New booking: Priya, Sat 8 PM, 4 people + catering quote request"}
```
Then, each step logged in `messages` or on the call, and safe to retry on its own:
1. **CRM:** upsert the contact by phone number (name, language, stage, tags, last call, calls count, call permission); save what changed in `calls.crm_changes`.
2. **External CRM:** if the business set `crm_webhook_url`, POST the contact + call JSON there (n8n, Zapier, Make, Sheets, HubSpot through those).
3. **Follow-up:** the approved template in the caller's language. Templates work whether or not a call opens WhatsApp's 24-hour chat window (Meta's docs don't say).
4. **Owner alert:** if the business set `owner_whatsapp`, send `owner_new_lead`.

### Templates (`templates.py`)
Created with `POST /<WABA_ID>/message_templates`, category `utility`, in every business language. Approval takes up to 24 hours, so **create them on Day 3**.
| Name | Body (English; translated per language) | Button |
| --- | --- | --- |
| `booking_confirmed` | Hi {{1}}, your booking at {{2}} is confirmed for {{3}}. Reply here if you need to change it. | |
| `booking_reminder` | Hi {{1}}, a reminder of your booking at {{2}} today at {{3}}. See you soon. | |
| `booking_changed` | Hi {{1}}, your booking at {{2}} is now {{3}}. | |
| `message_received` | Hi {{1}}, thanks for calling {{2}}. We got your request and will update you here soon. | |
| `task_done` | Hi {{1}}, an update from {{2}} on your request: {{3}} | |
| `call_thanks` | Hi {{1}}, thanks for calling {{2}}. Reply here anytime if you have more questions. | |
| `call_us` | Hi {{1}}, {{2}} would like to talk to you. Tap below to call us on WhatsApp. | `voice_call` "Call Now" |
| `owner_new_lead` | New call at {{1}}: {{2}} | |

`call_us` rules from Meta: the `voice_call` button can't be combined with other buttons, no footer, `ttl_minutes` 1440-43200. Older WhatsApp apps get error 131026. If Meta rejects the button, the dashboard falls back to sending the call link as text.

`python templates.py create` creates them all; `python templates.py status` shows approved, pending or rejected.

## Calling buttons
| Button | Where | How | When it works |
| --- | --- | --- | --- |
| **Call link** `https://wa.me/call/<number>?biz_payload=<source>` | Public page `/c/<slug>`, QR code on the setup page, website, posters | No API; WhatsApp opens a call to the business. `biz_payload` comes back as `deeplink_payload` and is saved as the call's `source` | Phones only (not WhatsApp desktop) |
| **Call Now in WhatsApp** | Dashboard: call detail, contact, task ("Send call button") | `POST /api/contacts/{id}/call-button`: interactive `voice_call` message if the customer wrote in the last 24 h (`last_inbound_at`), else the `call_us` template | Always, once `call_us` is approved |
| **AI call back** (stretch) | Contact page | `POST /api/contacts/{id}/callback`: business-initiated `connect` with our SDP offer, the AI calls with the given purpose | Only if the customer gave call permission (they called us with `callback_permission_status` on); otherwise 409 and the UI offers the call button |

## Login, signup and businesses (`auth.py`)
- **Signup** creates a business (with a unique `slug` from its name) and its first user, the `owner`. If `SIGNUP_CODE` is set, signup needs it, which keeps strangers out during the hackathon.
- **Login** checks the password (argon2id, `argon2-cffi`), then creates a session: a random 32-byte token returned to Next.js, stored only as a SHA-256 hash, expires after 7 days. Logout deletes it.
- **Every `/api` route** (except signup, login, public) loads the user from the Bearer token and only touches rows with that user's `business_id`. `staff` can't `PUT /api/business`.
- **Rate limit:** 5 login or signup tries per minute per email (in memory), then 429.
- **WhatsApp per business:** each business stores its `wa_phone_number_id` (from Meta's API Setup page, entered on the setup page). Webhooks are routed by `metadata.phone_number_id`. One app token (`WHATSAPP_TOKEN`) serves all numbers on our WhatsApp account; for the hackathon that's one business on the test number. Real multi-business onboarding (Embedded Signup) comes after the hackathon.

## Database (SQLite, `backend/app.db`)
```sql
businesses (id INTEGER PRIMARY KEY, slug UNIQUE, name, wa_phone_number_id UNIQUE, wa_display_number,
            timezone,            -- e.g. Asia/Kolkata; the VPS clock is UTC
            hours, slot_minutes, seats_per_slot, menu, prices, faqs, languages,
            owner_whatsapp, crm_webhook_url, created_at, updated_at)
users      (id INTEGER PRIMARY KEY, business_id, name, email UNIQUE, password_hash,
            role,                -- owner | staff
            created_at, last_login_at)
sessions   (id INTEGER PRIMARY KEY, user_id, token_hash UNIQUE, expires_at, created_at)
contacts   (id INTEGER PRIMARY KEY, business_id, wa_user_id, phone, name, language,
            stage,               -- new | lead | booked | customer
            tags, notes, first_call_at, last_call_at, last_inbound_at, auto_reply_at, calls_count, call_permission,
            UNIQUE (business_id, wa_user_id))   -- phone can be empty for username users
calls      (id INTEGER PRIMARY KEY, business_id, contact_id, wa_call_id UNIQUE,
            direction,           -- inbound | outbound
            source,              -- website | qr | followup | null
            language, started_at, ended_at, duration_s,
            outcome,             -- booked | task | answered | busy | missed
            summary, crm_changes, tokens_in, tokens_out, audio_seconds, cost_usd)
transcripts(id INTEGER PRIMARY KEY, call_id, role, text, language, at)   -- role: caller | agent
bookings   (id INTEGER PRIMARY KEY, business_id, contact_id, call_id, name, party_size, slot, note,
            status,              -- booked | changed | cancelled
            reminder_sent_at, created_at, updated_at)
tasks      (id INTEGER PRIMARY KEY, business_id, contact_id, call_id, type, details,
            urgency,             -- normal | urgent
            status,              -- open | done
            done_note, done_by, created_at, done_at)
messages   (id INTEGER PRIMARY KEY, business_id, contact_id, call_id, booking_id, task_id,
            kind,                -- followup | reminder | booking_changed | task_done | owner_alert | call_button | auto_reply
            template, language, body, wa_message_id, status, error, sent_at)
```
Cost per call = Muse Spark tokens × price + audio seconds × $0.18 / 3600. MMS is free.

No separate database server: SQLite is one file on the VPS. A daily cron copies it to `backups/app-<date>.db` (keep 7); download one before the VPS month ends. Postgres only when this becomes a real multi-business SaaS.

## Settings (`backend/.env`, never read or printed)
| Name | Needed | What |
| --- | --- | --- |
| `MODEL_API_KEY` | yes | Muse |
| `WHATSAPP_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_WABA_ID` | yes | WhatsApp app (one for all businesses) |
| `WHATSAPP_PHONE_NUMBER_ID` | yes | Test number; scripts use it, and the first business gets it by default |
| `BACKEND_API_KEY` | yes | Shared secret with the Netlify dashboard |
| `SIGNUP_CODE` | optional | When set, signup needs it |
| `LLM_MODEL` | default `muse-spark-1.3` | Chat model |
| `MAX_CALLS` | default 3 | Live calls at once |

Owner alert number and CRM webhook are per business, on the setup page, not in `.env`.

## Credit rules (in code, not just in prompts)
- Spoken replies: 120 tokens, minimal reasoning. Post-call: one call, 400 tokens.
- Fixed system prompt under 400 words. Last 8 turns only. One Transcribe session per call.

## Errors
- Catch at the edges (webhook, Muse, Transcribe, TTS, WhatsApp send, CRM webhook). Log and keep the server up.
- Muse fails mid-call: a fixed "Sorry, one moment" line, retry once, then take a message.
- A WhatsApp send or CRM webhook fails: mark the row `failed` (the dashboard shows it), retry once after 1 minute.
- Never log tokens, passwords, keys or full phone numbers.

## One server: what runs where
```
Meta's cloud                           Our VPS (2 vCPU, 4 GB)                          Netlify
  WhatsApp Cloud API  --HTTPS webhook-->  uvicorn :443, 1 process, 1 worker    <--/api--  Next.js dashboard
  Muse Spark (LLM)    <--HTTPS----                    FastAPI routes + auth
  Muse Transcribe     <--WSS------                    Pipecat call bots (1 per live call)
                      <--UDP audio-->                 MMS voices (loaded once, shared)
                                                      scheduler, SQLite file, daily backup
```
- Heavy AI runs at Meta; the VPS moves audio, runs the small MMS voices and stores data.
- **One uvicorn process, one worker** (more workers would load the voices again and run out of RAM). MMS runs in a thread pool so it never blocks other calls.
- **`MAX_CALLS`** (default 3): extra callers hear "all our lines are busy, please leave a message" and still get a follow-up.
- One service: `wa-backend` (uvicorn, serving HTTPS itself), systemd, restarts on crash and reboot. No proxy, no tunnel.

## Run on the Mac (quick checks)
```bash
cd ~/Hackathon/backend && .venv/bin/pip install -q -r requirements.txt
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

## VPS (Bluehost, 2 vCPU, 4 GB RAM)
Memory budget: Python + torch + Pipecat ≈ 1-1.5 GB, three MMS voices ≈ 0.5 GB, each live call ≈ 100-200 MB. Fits 2-3 calls at once; add a 2 GB swap file.

Setup, once (Ubuntu 22.04 or 24.04; AlmaLinux works with `dnf` instead of `apt`):
1. SSH in as root, create a user, add a 2 GB swap file.
2. Install Python 3.12, git and ffmpeg.
3. `git clone` the repo, create `backend/.venv`, first `pip install torch --index-url https://download.pytorch.org/whl/cpu` (CPU-only build), then `pip install -r requirements.txt`. Copy `backend/.env` with `scp` (never through git).
4. HTTPS without a proxy: at your domain registrar, add an A record `api` → the VPS IP. **You install the SSL certificate on the server yourself**; the backend only needs the certificate and key file paths, readable by the service user. Renewing it before it expires is on you too (restart `wa-backend` after a renewal). systemd service `wa-backend`: uvicorn on `0.0.0.0:443` with `--ssl-certfile` and `--ssl-keyfile`, `AmbientCapabilities=CAP_NET_BIND_SERVICE` so it can use port 443 without running as root.
5. Firewall: allow SSH, TCP 443 (HTTPS), TCP 80 only if your certificate method needs it, and the UDP port range Pipecat uses for call audio (check Pipecat's WhatsApp docs at step 3).
6. Daily cron for the SQLite backup.

Deploy a change: `git pull && sudo systemctl restart wa-backend`. Before the domain is set up: run uvicorn on plain HTTP port 8000 and check `http://<VPS IP>:8000/health` from your Mac. Meta's webhook needs the HTTPS domain.

## Step checks
| Step | Check |
| --- | --- |
| 1 | `muse_check.py` prints a Muse reply and tokens |
| 2 | `/health` answers on `api.<domain>`; Meta "Verify and save" passes; a test event appears in the log |
| 3 | Phone call is answered and plays the greeting; templates submitted |
| 4 | Spoken English and Hindi print live, one line per turn |
| 5 | 3-turn conversation in English, then in Hindi, replies under 2 s |
| 6 | "Table for 4, Saturday 8 PM" is booked and read back; "kal raat 8 baje" resolves to the right date; a full or closed slot gets alternatives; "quote for 40 people" creates a task; "let me talk to someone" creates an urgent callback task |
| 7 | Hang up → confirmation in the caller's language → contact updated → owner alert; reminder 3 h before; task done sends `task_done`; texting the number gets one Call Now reply; a second call is greeted by name |
| 8 | Signup, login, logout work; another business's data returns 404; staff can't edit setup; every endpoint in [api.md](api.md) answers as listed; "Send call button" arrives on the phone |
| 9 | 10 calls in a row (mixed languages) with no crash; cost per call in `/api/calls` |

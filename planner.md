# Build plan

Ship a multilingual WhatsApp AI calling agent for Meta's Global AI Developer Hackathon (indie track). Submissions close **4 Nov 2026, 9 PM US Eastern (5 Nov, 7:30 AM India)**; aim to finish a day early.

| Plan | What's in it |
| --- | --- |
| [api.md](api.md) | Every endpoint: backend, outside APIs, dashboard routes |
| [backend.md](backend.md) | Voice, LLM, tasks, automation, call buttons, login, database, VPS |
| [frontend.md](frontend.md) | Next.js pages, login and signup, buttons, Netlify |

## Official rules (what they mean for us)
| Rule | What we do |
| --- | --- |
| **New work only** (built 26 Oct to 4 Nov) | All code starts 27 Oct; git history proves it. Nothing from earlier projects is copied in. |
| **Identify your contributions** (or disqualified) | README section "Built during the hackathon" listing our code, and "Not ours" listing open-source parts (Pipecat, MMS voices, Next.js, FastAPI, Ponytail skill). The demo only shows our features. |
| **Public repo** | Private while building; on Day 9 scan the full git history for secrets, then make it public. Keys, `.env*`, databases and backups are git-ignored. |
| **One track** | Indie Developer. |
| **3-minute demo video** (one of the main scores) | Script below, **under 3:00**, recorded on a real phone. |
| **No rights problems** | Credit every open-source part and its licence in the README. MMS voices are CC-BY-NC: used only for this non-commercial demo, credited, and replaced before selling. |
| **Not a banned or generic idea** | A multilingual voice agent that answers and finishes work for real businesses isn't on the list. We avoid the banned areas (no medical or health advice). |
| **Platform policies** | The agent says it's the business's AI assistant at the start of every call; test calls only. |
| **Theme** | **Build for Your World**: Indian small businesses get calls in Hindi, Tamil and English on WhatsApp and miss many of them; Meta's models answer, book and follow up. |
| **Eligibility** | You confirm: 18+ and not Meta or Cerebral Valley staff, contractor or household. |
| **Submit** by Wed 4 Nov, 9 PM ET | [cerebralvalley.ai submit page](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit): public repo, working video link. |

## How we're judged
Indie track: creativity, technical ambition, and whether it works. The demo video is one of the main scores. "Whether it works" beats features: a live call that never breaks wins over a long feature list.

## What the demo must show (video under 3:00)
Demo business: **Your Cafe**.
1. A customer taps **Call us on WhatsApp** (QR code on the cafe's page) and speaks **Hindi mixed with English**: "Table for 4 on Saturday at 8, and I need a quote for a 40-person party on Sunday." The AI answers in Hindi, in a natural voice.
2. During the call: it checks free slots, books the table and reads it back, and turns the party request into a task.
3. Seconds after hang-up: the customer gets a booking confirmation in Hindi; the owner gets "New booking + catering quote request".
4. The owner logs in to the dashboard: the call (transcript, summary, cost about 3 cents), the booking, the open task, the new CRM contact. They mark the task done with a quote, and the customer's phone gets it on WhatsApp, live on camera.
5. A second short call in English or Tamil (opening hours, then cancelling the booking) to show it's not a one-language trick.

## Rules that shape every step
- **Meta AI in the product:** Muse Spark (thinking), Muse Voice Transcribe (hearing), Meta MMS open voices (speaking; the Model API has no TTS).
- **Credits:** Muse $150 free (about 3 cents per 3-minute call).
- **Each step:** plan in 5 lines, build, run its check, show the result, commit. Nothing outside backend.md, frontend.md and api.md.

## How it fits together
```
Customer phone --WhatsApp call--> Meta Cloud API --webhook (HTTPS)--> VPS: FastAPI :8000
   (call link, QR, Call Now button)              <--WebRTC audio (UDP)----> VPS: Pipecat call bot
  call:   audio -> Muse Transcribe (end of turn, 25 languages) -> Muse Spark (+ tools) -> MMS voice (per language)
  after:  transcript -> Muse Spark JSON -> CRM -> WhatsApp template (caller's language) -> owner alert
Owner/staff browser --> Netlify: Next.js (login) --HTTPS, X-API-Key + session--> VPS: FastAPI /api --> SQLite
```
**Hosting:** Bluehost VPS (2 vCPU, 4 GB RAM, 1 month) runs FastAPI, Pipecat, the MMS voices and SQLite. Netlify runs the Next.js dashboard. A domain record `api.<domain>` points at the VPS, and the backend serves HTTPS itself with the certificate you install on the server (no proxy, no tunnel).

## Timeline
| Day | Date | Step | Done when | Owner |
| --- | --- | --- | --- | --- |
| 2 | 27 Oct | Setup | Tools, agent rules, models.py, Ponytail, plans | ✅ done |
| 3 | 28 Oct | Accounts | VPS reachable over SSH, private GitHub repo, `api.<domain>` pointing at the VPS | You (AI sets up the VPS) |
| 3 | 28 Oct | 1. Muse check | `muse_check.py` prints a Muse reply and tokens | You: key · AI |
| 3 | 28 Oct | WhatsApp app | Test number, token, IDs in `.env`; calling ENABLED | You |
| 3 | 28 Oct | 2. Webhook | `/health` and "Verify and save" pass on `api.<domain>` | You + AI |
| 3 | 28 Oct | Templates | All 8 templates submitted (approval up to 24 h) | AI, then you check |
| 4 | 29 Oct | 3. Answer a call | Your call is answered and hears an MMS greeting | You: call · AI |
| 4 | 29 Oct | 4. Hearing | English and Hindi speech print live | AI |
| 5 | 30 Oct | 5. Talking | Full conversation in English and Hindi, replies under 2 s | AI · You: judge voice |
| 6 | 31 Oct | 6. Business brain | Books, moves and cancels tables; creates tasks | AI · You: cafe info |
| 7 | 1 Nov | 7. Automation | Confirmation, CRM, owner alert, reminders, task done → customer notified | AI |
| 8 | 2 Nov | 8. API, login, dashboard, call buttons | Everything in [api.md](api.md) works; signup/login; 7 dashboard pages on Netlify; call link, QR and Send call button | AI |
| 9 | 3 Nov | 9. Polish | 10 mixed-language test calls pass; cost per call shown | You: calls · AI: fixes |
| 9 | 3 Nov | README + public repo | README rewritten (what it is, how to run, "Built during the hackathon", "Not ours" with licences); history scanned for secrets; repo public | AI, then you |
| 9 | 3 Nov | Demo video | Script above, under 3:00, recorded on a real phone, uploaded (unlisted is fine) | You |
| 10 | 4 Nov | Submit | Checklist below, submitted before evening India time | You |

Day 2 slipped into Day 3, so Day 3 is the heaviest setup day. Step 8 is the heaviest build day: start the backend API part on 1 Nov evening if step 7 finishes early.

**Gate:** step 3 (a real call answered with audio) must work by end of 30 Oct; everything else depends on it.

If a day slips, cut in this order: owner alert → reminders → contact detail page → third language. Never cut steps 1-7, login, or the call link.

## Submission checklist (4 Nov)
- [ ] Repo public, README has "Built during the hackathon" and "Not ours" (with licences)
- [ ] No secrets in the repo or its history
- [ ] Video under 3:00, link opens without login
- [ ] Track: Indie Developer; theme: Build for Your World
- [ ] Submitted on the Cerebral Valley page before 9 PM ET (7:30 AM 5 Nov India)

## What only you can do
- Keys and IDs into `backend/.env` yourself ([setup/muse_api.txt](setup/muse_api.txt)).
- Meta dashboard: app, test number, recipients, token, webhook, field subscriptions.
- VPS: run `ssh-copy-id` once so the AI agent can set it up; open UDP in the Bluehost firewall if it has one.
- A domain with an A record `api` → the VPS IP, and the SSL certificate for `api.<domain>` installed on the VPS; Netlify account linked to GitHub.
- Test calls from real phones, judge the voice, record and submit.

## Working loop (terminal, `~/Hackathon`)
1. `/clear`
2. `Read backend.md and do step N. Plan first.`
3. Approve the plan, let it build, run the check it gives you.
4. When it works: `commit this step`.

## Risks
| Risk | What we do |
| --- | --- |
| Real numbers need a 2,000/day messaging limit for calling | Use Meta's test number. Real number after the hackathon. |
| Test number may only work with the 5 numbers in its "To" list | Add every demo phone. Judges watch the video; don't promise a live call to strangers. |
| **Call audio (WebRTC/UDP) can't reach the server: the make-or-break risk** | Step 3 on 29 Oct is the gate. Bot on the VPS with a public IP and UDP open. If audio isn't flowing by end of 30 Oct, stop everything else, ask in Pipecat's GitHub issues and Discord, and try a WhatsApp provider (360dialog) |
| Template rejected or slow (up to 24 h); `voice_call` button may not be available everywhere | Submit on Day 3; plain utility wording. If `call_us` is rejected, send the call link as text. |
| MMS voice sounds flat | Judge on Day 5. Short sentences, natural fillers. The trade-off goes in the write-up. |
| Tool calls unreliable at minimal reasoning (wrong dates, missed bookings) | Tools take strict ISO dates; today's date in context; agent reads every booking back; step 6 tests Hindi dates. Raise `reasoning_effort` to `low` if needed |
| Step 8 overloaded (API, login and dashboard in one day) | Build `db.py` and the read endpoints as each step needs them (steps 2-7), so step 8 is mostly login and pages |
| Server down = calls show "Not answered" | systemd restarts; free uptime monitor on `/health` emails you; don't touch the server on demo day |
| Slow replies (STT + LLM + TTS on a CPU VPS) | Muse endpointing, sentence-by-sentence TTS, minimal reasoning. Target under 2 s. |
| VPS far from callers | Measure on Day 5; move to a Mumbai or Singapore VPS if needed (same setup steps). |
| VPS lost after 1 month | Code in git, SQLite backed up daily, setup steps in backend.md. |
| Strangers sign up on the public dashboard | `SIGNUP_CODE` set during the hackathon. |
| Free-credit content may be used by Meta | Test calls only, no real customers. |
| Judges can't tell what's new (disqualification) | Commits dated in the event, README contribution sections, demo shows only our features. |
| Secret leaks when the repo goes public | `.env*` ignored (fixed 28 Oct); history scan before publishing. |

## Open questions
- [x] Track: **Indie Developer**. Theme: **Build for Your World**.
- [ ] You: confirm you're 18+ and not Meta or Cerebral Valley staff, contractor or household.
- [x] Demo business: **Your Cafe**. Languages: English + Hindi + Tamil.
- [ ] External CRM: none (built-in contacts), Google Sheets, HubSpot, Zoho? (The CRM webhook URL on the setup page covers all via n8n/Zapier.)
- [x] Hosting: Bluehost VPS 2 vCPU / 4 GB, dashboard on Netlify, SQLite on the VPS.
- [ ] VPS: operating system, region, UDP ports open? Domain name?
- [ ] KX UI colour values.

## If time is left (in this order)
1. AI call back button (business-initiated call; needs the customer's permission).
2. Live "call in progress" badge on the dashboard.
3. Invite staff logins from the setup page.
4. Weekly WhatsApp report to the owner (calls, bookings, cost).

# Shopping agents dashboard: build instruction

You are building this now, in one run, in this repo. This file replaces `STORE_BUILD.md` and every earlier instruction, including any fixes still pending. Work through the phases in order. Do not stop for approval unless a section says **STOP**.

## What we are building

No store. One logged-in dashboard where a team of agents shops for the user:

1. The user drops a photo of a shirt.
2. Agents identify it, search the internet for similar items, check price and stock on each listing, and rank them.
3. With one click, the agent sends the seller a WhatsApp template asking if the item is still in stock.
4. The user clicks **Place order**. The agent sends the order to the seller on WhatsApp.
5. The agent picks the best delivery option, then tracks the order until it arrives.

Payment stays between the user and the seller, such as cash on delivery. This app never takes or stores card, bank or UPI details, and never logs in to or checks out on a seller's website.

## Rules for the whole run

- Smallest change that works. No extra features, abstractions or config layers.
- Read only the files a phase touches. Never read `.venv`, `node_modules`, model weights or whole logs.
- Keys come only from `backend/.env`. Never print, log or commit their values. To check keys, print only which names are empty.
- The repo is public. Never commit `.env*`, databases, uploaded photos or real customer or seller data. Add ignore rules before creating such files.
- Meta models only: `muse-spark-1.3`, `sam-3.1`, `muse-voice-transcribe-1.0`, `facebook/mms-tts-<lang>`. No other search or AI APIs.
- Catch errors at the edges and log them. One bad page or API error must never crash the server. Webhooks return 200 fast and do slow work in a background task.
- No blocking calls on the main server loop. Use `asyncio.to_thread` or a background task.
- Selfchecks must never touch the network or send a message. Stub WhatsApp and model calls. A check that skips itself counts as failed.
- Create `backend/.venv` locally (git-ignored) with Python 3.12 and the light dependencies, so auth and database checks really run here.
- End each phase by running its check, printing the output, then committing and pushing with a short message. If a check fails, fix it within the phase. Otherwise take the phase's fallback and report it.
- Don't claim something works unless you ran it. Say clearly what only a real phone can prove.
- Spend limit during this build: at most 5 real hunts. Use stubs for everything else.

## These safety rules are not optional

**1. Web pages and seller messages are untrusted data.**
- Any model call that reads a page or seller message gets no function tools and returns structured output only.
- Text in a page or message can never choose a recipient, change a price, or trigger a send.
- Only code acts, using values from our database, after a logged-in user clicks.
- Show untrusted text escaped, and label it as coming from the seller or the page.

**2. Only message sellers who agreed.** WhatsApp policy requires that the person gave their number and opted in. Hackathon rules disqualify projects that break platform policy.
- Never message a number found on a website, and never send without `opted_in = 1`.
- A seller is added in the dashboard by a logged-in user, with a required checkbox: "This seller agreed to receive WhatsApp messages from us."
- A seller who replies STOP gets `opted_in = 0` straight away and is never messaged again.
- Limits: 1 stock check per seller per hunt, and 5 template messages per seller per day.
- For a listing with no opted-in seller, show **Open listing**. If the page shows a WhatsApp number, also show **Ask from my WhatsApp**, a `wa.me` link with the text filled in, which the user sends from their own phone.

**3. Prices and stock must be real.**
- Use only URLs returned by the search tool, never URLs written by the model.
- Each price and stock status must come from the fetched page: JSON-LD `Offer`, `product:price` meta tags, or an exact quote that code confirms is on the page. Otherwise show "Price not verified" and "Stock not verified".
- Rank verified listings first. Say "Best verified price of the N listings checked". Never claim the lowest price on the internet.

**4. Fetch pages politely and safely.**
- Allow only public `http` and `https` URLs. Block private, loopback and link-local addresses, including after redirects. Timeout 10 s, 2 MB limit, at most 3 redirects.
- Respect `robots.txt`. Never bypass logins, captchas or bot protection. If blocked, mark the listing "Couldn't check" and move on.
- Don't save images from other sites. Link to the listing and load its image only for the comparison step and the results card.

**5. Orders always need a person.**
- Every order needs a click on a confirmation screen showing the item, seller, price, delivery choice, name and address.
- The delivery address goes to the seller only when that click happens.

**6. Hunt limits.** Per hunt: at most 3 searches and 12 candidates. Per user: 1 hunt running at a time and 20 per day. Save tokens, searches and cost on each hunt, and show them on the hunt page.

## Time plan

| Phase | Work | Minutes |
|---|---|---:|
| 0 | Remove the store, submit templates | 15 |
| 1 | Make the dashboard build | 20 |
| 2 | Hunt agents | 45 |
| 3 | Seller messages | 30 |
| 4 | Order, delivery, tracking | 30 |
| 5 | Dashboard screens | 40 |
| 6 | Deploy, full test, README | 20 |

If behind schedule, cut in this order: SAM crop, automatic tracking reminders, cost display. Never cut the safety rules, the confirmation screen, the secret scan, or the real end-to-end test.

## Phase 0: Remove the store, submit templates (15 min)

Do this first, because template approval can take up to 24 hours and the deadline is tonight.

1. Copy `store/public/products/tee-white.jpg` to `backend/hunt_test/shirt.jpg`. Add `backend/hunt_test/` and `backend/data/` to `.gitignore` first.
2. Delete `store/`, `STORE_BUILD.md`, `backend/store.py`, `backend/seed_escape.py`, `backend/outbound_test.py`, and the `/api/public/orders`, `/api/public/products` and `/api/public/tryon` routes and their CORS setup.
3. Remove the ESCAPE prompt, store tools, `tools_for` and order fields from `agent.py` and `voice_call.py`, so the voice agent uses its normal prompt and tools. In `voice_call.py`, run `agent.run_tool` in `asyncio.to_thread`. In `voice_stt.py`, stop logging caller speech: log text length only.
4. In `outbound.py`, keep only `creds`, `_call`, `GraphError` and `send_text`. Add `send_template`. Remove the outbound call webhook hook in `main.py`, along with the ORDER and button handling.
5. Add `backend/owner_setup.py <business_slug> <email>`:
   - Creates the business and owner if missing, asking for the password with `getpass`. If the email already exists, says so and doesn't change it.
   - Moves `WHATSAPP_PHONE_NUMBER_ID` and `WHATSAPP_DISPLAY_NUMBER` to that business. Sets any other holder of the number to `NULL`, in one transaction.
6. Make `SIGNUP_CODE` required: when unset, signup returns an error.
7. Add these templates in `templates.py`, English only, category UTILITY. Add a `create <name>` option so only these are submitted. A template body can't start or end with a variable.
   - `stock_check`: "Hello {{1}}, a customer is asking about {{2}} in size {{3}}. Listing: {{4}}. Is it still in stock, and what is your final price with delivery to {{5}}? Thank you." Quick-reply buttons: `In stock`, `Out of stock`.
   - `order_request`: "Hello {{1}}, please confirm this order for {{2}}, size {{3}}, at {{4}}. Deliver by {{5}} to {{6}}, {{7}}, phone {{8}}. Payment is {{9}} directly to you. Please reply to confirm." Quick-reply buttons: `Confirm order`, `Can't fulfil`.
   - `tracking_request`: "Hello {{1}}, could you share the courier and tracking number for order {{2}}? Thank you."

**Check:** selfchecks pass, no store references remain (`grep`), and the voice agent selfcheck still passes. Push, print the VPS commands below for the owner, and **continue without waiting**:

```bash
cd /home/wa/Probetests && git pull && systemctl disable --now escape-store && rm -f /etc/systemd/system/escape-store.service && systemctl daemon-reload
```

```bash
cd /home/wa/Probetests/backend && .venv/bin/python voice_tts.py selfcheck && .venv/bin/python agent.py selfcheck && .venv/bin/python voice_call.py selfcheck && systemctl restart wa-backend && systemctl is-active wa-backend && .venv/bin/python templates.py create stock_check && .venv/bin/python templates.py create order_request && .venv/bin/python templates.py create tracking_request
```

## Phase 1: Make the dashboard build (20 min)

`dashboard/` has only `src/` and `.env.example`. Add `package.json`, `next.config.js`, `tsconfig.json`, and Tailwind and PostCSS config only if the code uses them.

- Use `next@15.5.29` and the latest patched `react@19`, with exact versions. Update `cookies()`, `headers()`, `params` and `searchParams` for Next 15.
- Set `images: { unoptimized: true }`, and `experimental.serverActions.bodySizeLimit: "9mb"` so photos can upload.
- `BACKEND_API_KEY` and `BACKEND_URL` stay server-side only.

**Check:** `npm run build` passes, and `npm audit --omit=dev` shows no critical or high findings. Report anything left.

## Phase 2: Hunt agents (45 min)

Read these first:
- https://dev.meta.ai/docs/search-grounding
- https://dev.meta.ai/docs/image-understanding
- https://dev.meta.ai/docs/structured-output
- https://dev.meta.ai/docs/sam/segmenting

Create `backend/hunt.py`, with tables `hunts`, `hunt_steps` and `listings`. Every table is scoped by `business_id`, and every route uses the session check. A hunt runs in a background task, and each agent writes real steps to `hunt_steps`. On startup, mark hunts left running as failed.

`POST /api/hunts`:
- Accepts JPEG, PNG or WebP up to 8 MB, plus optional size and budget.
- Re-encodes the image to strip metadata and saves it under `backend/data/hunts/`.
- Photos are deleted after 7 days and served only through a logged-in route.

The agents:

1. **Spotter:** use `sam-3.1` to crop to the garment, or use the full photo if that fails. Send it to `muse-spark-1.3` with structured output: garment type, colour, pattern, fabric, collar, sleeve, fit, brand if clearly visible, and 3 search phrases. If the photo shows no garment, stop with a clear message.
2. **Finder:** use the Responses API with `{"type": "web_search", "user_location": {"type": "approximate", "country": "IN"}}` and `include: ["web_search_call.results"]`. Run 3 narrow searches, using the country from Setup. Keep only product pages from the returned results, and remove duplicates. Keep at most 12. Search can return nothing, so handle that.
3. **Checker:** fetch each page under safety rule 4. Extract price, currency, stock, delivery text, seller name, image and any WhatsApp number under safety rule 3.
4. **Matcher:** send the cropped photo and candidate images to `muse-spark-1.3` with structured output: a similarity score from 0 to 100 and a one-line reason for each. Remove anything under 60.
5. **Ranker:** this is plain code, not a model. Sort by verified first, then in stock, then lowest price plus delivery, then similarity. Give a short reason for the top pick.

Set the model's reasoning effort low, because thinking counts against the token limit and short caps can return empty text. Check this with the docs and with one real request.

Routes: `GET /api/hunts`, `GET /api/hunts/{id}` (with steps and listings), and a logged-in route for the photo.

**Check:** selfchecks use saved sample HTML for JSON-LD extraction, private address blocking, invented URL rejection, quote checking, ranking, and business isolation. Then run one real hunt on `backend/hunt_test/shirt.jpg` and print the listings and cost. Say honestly how many were verified.

**Fallback:** if search finds too few product pages, add one more search on Indian shopping sites and report the result. Never invent listings.

## Phase 3: Seller messages (30 min)

Add table `sellers` (name, phone, `opted_in`, `opted_in_at`, the user who added them) and `seller_messages`.

- Routes to add, edit and list sellers, and to link a seller to a listing.
- `POST /api/listings/{id}/stock-check`:
  - Requires a logged-in user, an opted-in seller and the limits in safety rule 2.
  - Fills `stock_check` from database values. Removes newlines and repeated spaces, and limits variable length.
  - The dashboard shows the exact message before the user clicks Send. That filled-in message is the "template" the agent creates for each item.
- If a template isn't approved, send the same text as a free-form message only if that seller messaged us in the last 24 hours. Otherwise show "Template waiting for approval", plus the `wa.me` option.

Webhook:
- If the sender matches a seller, handle the message in a background task and skip the Call Now auto-reply.
- Quick-reply buttons set the status directly.
- Free text goes through `muse-spark-1.3` with no tools and structured output: in stock, price, delivery options, tracking number, courier. Show this as what the seller said, and don't let it overwrite verified fields without the user seeing it.
- STOP sets `opted_in = 0`.

**Check:** selfchecks with WhatsApp stubbed:
- Not opted in means no send.
- STOP blocks later sends.
- Limits hold.
- A seller message containing instructions changes nothing except the parsed fields.
- A reply from an unknown number does nothing.

## Phase 4: Order, delivery, tracking (30 min)

Add table `purchases`. Statuses: `draft`, `order_sent`, `seller_confirmed`, `seller_declined`, `shipped`, `delivered`, `cancelled`, `needs_attention`. Reject any other change of status, and save a timeline entry for each change.

**Delivery agent (Picker):**
- Use the delivery options from the seller's reply or the verified page text.
- Apply the user's preference from Setup: cheapest, fastest, or arrive by a date. Picking by rule is plain code.
- Show the pick and the reason, and let the user change it on the confirmation screen.
- If there's only one option, say so. If there are none, ask the seller and don't guess.

**Buyer:** `POST /api/purchases` requires the confirmation values the user saw, and rejects the request if the price or seller changed since. It then sends `order_request`. Name, address and phone come from Setup. The seller's confirm or decline updates the status.

**Tracker:**
- A background check every 6 hours sends `tracking_request` at most once a day per seller order, only for confirmed orders with no tracking number.
- Also add an **Ask for update** button.
- Save the courier, tracking number and link from the seller's reply, and show them on a timeline. Only link to `https` tracking pages.
- Don't claim live courier status: show who said what and when.
- `delivered` is set by the user, or by the seller after the user confirms. After 3 unanswered reminders, set `needs_attention`.

**Check:** selfchecks for status rules, the price-changed rejection, delivery picks, and reminder limits.

## Phase 5: Dashboard screens (40 min)

Nothing should look like AI generated it. Style it like a careful printed ledger, not a SaaS template.

- Fonts: Newsreader for headings and Familjen Grotesk for interface text.
- Colours: warm paper `#F4F0E8`, ink `#1C1A17`, oxblood `#6E1F1B` used sparingly.
- Sharp corners or 2px at most, hairline rules instead of shadows, and a strict grid.
- **Never use:** gradients, glass effects, purple or blue accents, emoji, sparkle or robot icons, floating blobs, three-feature card rows, fake stats, "AI-powered", "seamless", "elevate" or "revolutionary".
- Motion only under 200 ms, and respect reduced motion. Build mobile first at 390 px, then 1440 px. Use keyboard-accessible, labelled controls, WCAG AA contrast, and real loading, empty and error states.

Navigation: **Hunts** (first), Orders, Sellers, Setup, Calls, Contacts, Tasks. Hide Bookings.

- **Hunts:** a large drop area with a file picker and optional size and budget. Next to it, a list of agents (Spotter, Finder, Checker, Matcher, Ranker, Messenger, Picker, Buyer, Tracker), each showing a real state and its last action from `hunt_steps`. Below that, past hunts. No fake progress: poll every 3 seconds while running.
- **Hunt page:** the user's photo, what Spotter saw, a table of listings (image, title, seller, price, stock, delivery, similarity, verified or not, source link), the top pick with its reason, and the cost. Actions: Ask seller, Add seller, Open listing, Ask from my WhatsApp.
- **Ask seller:** shows the exact message, then Send.
- **Place order:** the confirmation screen from safety rule 5, with cash on delivery or pay seller directly as the only payment choices.
- **Orders:** list and timeline with status, delivery pick, courier, tracking link and seller messages, plus Ask for update and Mark delivered.
- **Sellers:** add, edit, and show opted-in or opted-out status.
- **Setup:** delivery name, address and phone, delivery preference, country, and WhatsApp number status and template status (approved or pending).

**Check:** `npm run build` passes. Screenshot each page at 390 px and 1440 px, list anything that looks templated, fix it, and save the screenshots outside git.

## Phase 6: Deploy, full test, README (20 min)

The dashboard replaces the store at `probetests.space`. Print these VPS steps for the owner. Each setup step should only be needed once:

```bash
cd /home/wa/Probetests && git pull && cd backend && .venv/bin/pip install -r requirements.txt && for f in voice_tts.py agent.py voice_call.py hunt.py; do .venv/bin/python $f selfcheck || break; done
```

```bash
umask 077 && { grep '^BACKEND_API_KEY=' /home/wa/Probetests/backend/.env; echo 'BACKEND_URL=http://127.0.0.1:8000'; } > /etc/wa-dashboard.env
```

Also print these, using the real file names you commit:
- A systemd unit in `deploy/wa-dashboard.service`: user `wa`, working directory `dashboard/`, `next start -H 127.0.0.1 -p 3000`, `EnvironmentFile=/etc/wa-dashboard.env`.
- A build as user `wa`, using `su -s /bin/bash wa -c '...'`. `sudo` is broken on this server.
- A command adding `client_max_body_size 9m;` to `/etc/nginx/sites-available/probetests.space`, keeping the existing `/_next/image` block, then `nginx -t` and a reload.
- `SIGNUP_CODE` added to `backend/.env` with a value the owner chooses, then a `wa-backend` restart.
- `owner_setup.py <slug> <email>`, run as user `wa`, with the password typed there by the owner.

Then **STOP** and wait for the owner to report that the deploy is done.

After that, give the owner this phone test. The owner needs a second phone as the test seller:
1. Message the business number from the seller phone, to open the 24-hour window.
2. Add that number as a seller and tick the agreement box.
3. Drop a shirt photo and wait for results.
4. Link the seller to a listing and send the stock check. Tap `In stock` on the seller phone.
5. Place the order and check the confirmation screen. Tap `Confirm order` on the seller phone.
6. Click Ask for update, then reply from the seller phone with a courier and tracking number.
7. Mark it delivered.
8. Reply STOP from the seller phone, and check that another send is refused.

Before any push, scan the working tree and full git history for secrets, uploaded photos and databases. **STOP** and report if anything is found.

Rewrite the README: what the project is, how the agents work, how to run it, what was built during the event, third-party code and licences, which Meta models are used and where, the safety rules above, and known limits. Be plain about these limits: search doesn't cover the whole internet, many shops block automated checks, sellers must opt in, and tracking comes from what sellers report.

**Final report:** a PASS/FAIL checklist with evidence for each item, separating what you ran from what the owner must test on a phone. List every cut and fallback.

Then tell the owner what is left for submission by the deadline, Wed Nov 4, 9:00 PM ET: public repo, working 3-minute demo video link, and every team member added.

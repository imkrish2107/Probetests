# Frontend (dashboard)

A Next.js dashboard on Netlify where the business owner and staff log in to see every call, booking, open task and customer (the CRM), send call buttons, and set up the business. Every endpoint it calls: [api.md](api.md). Built in step 8 (2 Nov). Overall plan: [planner.md](planner.md).

## Stack
- Next.js (App Router) + TypeScript + Tailwind: `npx create-next-app@latest dashboard --ts --tailwind --app --eslint --src-dir --use-npm`
- Hosted on **Netlify**. Pages are **server components**; forms and buttons use **server actions**. Both call FastAPI from the Next.js server at `BACKEND_URL` with `X-API-Key` and the user's session token. The browser never talks to FastAPI and never sees the key.
- `qrcode` (npm) for the call-link QR code. No UI kit, no state library.

## Login and signup
| Piece | How |
| --- | --- |
| `/signup` | Business name, your name, email, password (8+ characters), signup code (when the backend requires one). Server action → `POST /api/auth/signup` → sets the cookie → `/setup` |
| `/login` | Email, password. Server action → `POST /api/auth/login` → sets the cookie → `/` |
| Cookie | `session`: httpOnly, Secure, SameSite=Lax, 7 days. JavaScript can't read it |
| `middleware.ts` | No `session` cookie → redirect to `/login`. Public: `/login`, `/signup`, `/c/*` |
| Expired or revoked session | Any 401 from the API clears the cookie and redirects to `/login` |
| Logout | Button in the top bar → `POST /api/auth/logout` → clear the cookie |
| Roles | `staff` see the setup page read-only; only `owner` can save it |

## Look (KX UI)
- Background cream, text near-black, one accent colour. Placeholders until we get the KX UI tokens: background `#FAF6EE`, text `#1F1B16`, accent `#25D366` (WhatsApp green).
- Font: Red Hat Display via `next/font/google`, weights 400, 500 and 700.
- Rounded cards, plenty of white space; it should match our reels and carousels in the demo video.
- Language shows as a short pill (EN, HI, TA, TE, KN, BN, MR) so the multi-language part is obvious in the demo.

## Pages
| Route | Login | Shows | Buttons |
| --- | --- | --- | --- |
| `/login`, `/signup` | public | Forms above | Log in, Sign up |
| `/c/[slug]` | public | Business name, opening hours, big green **Call us on WhatsApp** button (the call link with `biz_payload=website`), QR code of the same link | Call |
| `/` Calls | yes | Today's totals (calls, bookings, open and urgent tasks, cost), calls table: customer (masked), language, source, when, length, outcome, cost. "Load more" pages through | |
| `/calls/[id]` | yes | Transcript bubbles (caller left, agent right), summary, bookings and tasks from this call, messages sent and their status, CRM changes, tokens, audio seconds, cost | **Send call button** |
| `/bookings` | yes | Day view (today, date picker): time, name, party size, note, status, reminder sent | **Move**, **Cancel** (customer gets `booking_changed`) |
| `/tasks` | yes | Open tasks, urgent first: type, customer, details, age | **Mark done** (asks for a note; customer gets it on WhatsApp), **Send call button** |
| `/contacts` | yes | Search, customers: name, number (masked), language, stage, tags, last call, calls count | |
| `/contacts/[id]` | yes | Details, editable stage, tags and notes; every call, booking, task and message | **Send call button**, **AI call back** (stretch; greyed out with "Customer hasn't allowed calls yet" when there's no permission) |
| `/setup` | yes, owner edits | Name, time zone, opening hours, slot length, seats per slot, menu (with allergens), prices, FAQs (word count, prompt under 400 words), languages, owner WhatsApp, CRM webhook URL, WhatsApp number ID and display number. **Your call link** with Copy and a QR download. Template approval status | **Save**, **Copy link**, **Download QR** |

Top bar on every logged-in page: Calls, Bookings, Tasks (with the open-task count), Contacts, Setup, the user's name, Log out.

## Files
```
dashboard/src/
  middleware.ts                 redirect to /login without a session cookie
  lib/api.ts                    fetch helpers + response types (server only): adds X-API-Key and Bearer token, handles 401
  lib/actions.ts                server actions: login, signup, logout, save setup, booking change, task done, call button, callback
  app/layout.tsx                font, colours
  app/(auth)/login/page.tsx
  app/(auth)/signup/page.tsx
  app/c/[slug]/page.tsx         public call page
  app/(app)/layout.tsx          top bar (uses /api/auth/me and /api/stats)
  app/(app)/page.tsx            calls
  app/(app)/calls/[id]/page.tsx
  app/(app)/bookings/page.tsx
  app/(app)/tasks/page.tsx
  app/(app)/contacts/page.tsx
  app/(app)/contacts/[id]/page.tsx
  app/(app)/setup/page.tsx
  app/globals.css
```
Every logged-in page uses `export const dynamic = "force-dynamic"` so new calls show on refresh. Buttons show a short result message ("Sent", "Failed: customer's WhatsApp is too old for call buttons").

## Run and ship
```bash
cd ~/Hackathon/dashboard && npm install --silent
npm run dev        # http://localhost:3000, against the local backend or https://api.<domain>
```
`dashboard/.env.local` (never committed): `BACKEND_URL`, `BACKEND_API_KEY`.

**Netlify:**
1. Push the repo to GitHub; Netlify → Add new site → Import from Git → pick the repo.
2. Base directory `dashboard`, build command `npm run build` (Netlify detects Next.js).
3. Environment variables: `BACKEND_URL=https://api.<domain>`, `BACKEND_API_KEY` (same as the backend's).
4. Every push to `main` redeploys. Optional: point `dash.<domain>` at the Netlify site.

The backend needs a fixed HTTPS URL for this: `https://api.<domain>`, served by the backend itself on the VPS (backend.md → VPS).

## Done when
- Signup → setup → a real call shows up on every page it should.
- Logged out, every private page redirects to `/login`; a staff user can't save setup.
- All buttons work against the real backend; the call button arrives on a phone.
- It works at phone width; empty states read well ("No calls yet", "Add your business info to start").

## If time is left
1. AI call back button (backend stretch).
2. Live "call in progress" badge: a client component polling `GET /api/live` every 2 seconds.
3. Invite staff: a team section on the setup page (`GET` / `POST /api/users`, `DELETE /api/users/{id}`).

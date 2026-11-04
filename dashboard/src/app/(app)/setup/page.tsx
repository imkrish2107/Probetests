import { api, sessionToken } from "@/lib/api";
import { get, Expired, PageHead, Status } from "@/lib/ui";
import { saveSetup } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Setup: owner edits business info; staff see it read-only (save 403s).
export default async function SetupPage({
  searchParams,
}: {
  searchParams: Promise<{ saved?: string; error?: string }>;
}) {
  const { saved, error } = await searchParams;
  const biz = await api("/api/business", undefined, await sessionToken());
  return (
    <main>
      <PageHead title="Setup" note="Where orders are delivered, how the agents choose, and your WhatsApp connection." />
      {saved && <p className="notice good">Saved.</p>}
      {error && <p className="notice">{error}</p>}
      <div className="split">
        <form action={async (fd) => { "use server"; await saveSetup(fd); }}>
          <section className="card">
            <h2 className="section-title">Delivery</h2>
            <p className="muted small">A seller sees these only when you confirm an order.</p>
            <label>
              Name
              <input className="input" name="delivery_name" defaultValue={biz.delivery_name ?? ""} autoComplete="name" />
            </label>
            <label>
              Address
              <textarea className="input" name="delivery_address" rows={2} defaultValue={biz.delivery_address ?? ""} autoComplete="street-address" />
            </label>
            <label>
              Phone
              <input className="input" name="delivery_phone" defaultValue={biz.delivery_phone ?? ""} autoComplete="tel" />
            </label>
            <div className="fields">
              <label>
                Picker should choose
                <select className="input" name="delivery_pref" defaultValue={biz.delivery_pref ?? "cheapest"}>
                  <option value="cheapest">Cheapest</option>
                  <option value="fastest">Fastest</option>
                  <option value="by_date">Arrive by a date</option>
                </select>
              </label>
              <label>
                Arrive by <span className="norm">if chosen</span>
                <input className="input" type="date" name="delivery_date" defaultValue={biz.delivery_date ?? ""} />
              </label>
              <label>
                Country
                <input className="input" name="country" defaultValue={biz.country ?? ""} placeholder="IN" />
              </label>
            </div>
          </section>
          <section className="card">
            <h2 className="section-title">Business and WhatsApp</h2>
            <label>
              Business name
              <input className="input" name="name" defaultValue={biz.name ?? ""} required />
            </label>
            <div className="fields">
              <label>
                WhatsApp number ID
                <input className="input" name="wa_phone_number_id" defaultValue={biz.wa_phone_number_id ?? ""} />
              </label>
              <label>
                WhatsApp display number
                <input className="input" name="wa_display_number" defaultValue={biz.wa_display_number ?? ""} />
              </label>
              <label>
                Owner WhatsApp
                <input className="input" name="owner_whatsapp" defaultValue={biz.owner_whatsapp ?? ""} />
              </label>
              <label>
                Time zone
                <input className="input" name="timezone" defaultValue={biz.timezone ?? ""} placeholder="Asia/Kolkata" />
              </label>
            </div>
          </section>
          <section className="card">
            <details>
              <summary>Voice agent settings</summary>
              <label>
                Greeting <span className="norm">what callers hear first, up to 300 characters</span>
                <textarea className="input" name="greeting" rows={2} defaultValue={biz.greeting ?? ""} />
              </label>
              <div className="fields">
                <label>
                  Slot length, minutes
                  <input className="input" name="slot_minutes" type="number" defaultValue={biz.slot_minutes ?? 30} />
                </label>
                <label>
                  Seats per slot
                  <input className="input" name="seats_per_slot" type="number" defaultValue={biz.seats_per_slot ?? 10} />
                </label>
              </div>
            </details>
          </section>
          <button className="btn" type="submit">
            Save
          </button>
          {biz.call_link && (
            <p className="small" style={{ marginTop: 14 }}>
              Call link: <a href={biz.call_link}>{biz.call_link}</a>
            </p>
          )}
        </form>
        <StatusCard />
      </div>
    </main>
  );
}

const TEMPLATES = [
  { name: "stock_check_v2", label: "Stock check" },
  { name: "quote_request_v2", label: "Quote request" },
  { name: "order_request_v2", label: "Order request" },
  { name: "tracking_request_v2", label: "Tracking request" },
  { name: "call_permission_v2", label: "Call permission" },
];

// Live template approvals from Meta (cached 5 min).
async function StatusCard() {
  const d = await get("/api/templates");
  if (d.expired) return <Expired />;
  const items: any[] = d.data?.items ?? [];
  return (
    <section className="sheet">
      <h2>WhatsApp templates</h2>
      <p className="muted small">
        Until a template is approved, the agents can message a vendor only if that vendor messaged
        you in the last 24 hours.
      </p>
      <ul className="agents">
        {TEMPLATES.map((t) => {
          const found = items.find((x) => x.name === t.name);
          const status = String(found?.status ?? "").toUpperCase();
          return (
            <li key={t.name}>
              <strong>{t.label}</strong>
              {found ? (
                <Status value={status === "APPROVED" ? "approved" : status === "REJECTED" ? "failed" : "queued"} />
              ) : (
                <span className="pill">Not submitted</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

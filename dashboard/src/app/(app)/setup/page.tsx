import { api, sessionToken } from "@/lib/api";
import { saveSetup } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Setup: owner edits business info; staff see it read-only (save 403s).
export default async function SetupPage({
  searchParams,
}: {
  searchParams: { saved?: string };
}) {
  const biz = await api("/api/business", undefined, sessionToken());
  return (
    <main>
      <div className="card">
        <h1>Setup</h1>
        {searchParams.saved && <p>Saved.</p>}
        <form action={saveSetup}>
          <label>
            Business name
            <input className="input" name="name" defaultValue={biz.name ?? ""} required />
          </label>
          <label>
            Greeting (what callers hear first, max 300 chars; blank uses the default)
            <textarea
              className="input"
              name="greeting"
              rows={2}
              defaultValue={biz.greeting ?? ""}
            />
          </label>
          <label>
            Time zone (IANA, e.g. Asia/Kolkata)
            <input className="input" name="timezone" defaultValue={biz.timezone ?? ""} />
          </label>
          <label>
            Slot length (minutes)
            <input
              className="input"
              name="slot_minutes"
              type="number"
              defaultValue={biz.slot_minutes ?? 30}
            />
          </label>
          <label>
            Seats per slot
            <input
              className="input"
              name="seats_per_slot"
              type="number"
              defaultValue={biz.seats_per_slot ?? 10}
            />
          </label>
          <label>
            Owner WhatsApp
            <input className="input" name="owner_whatsapp" defaultValue={biz.owner_whatsapp ?? ""} />
          </label>
          <label>
            WhatsApp number ID
            <input
              className="input"
              name="wa_phone_number_id"
              defaultValue={biz.wa_phone_number_id ?? ""}
            />
          </label>
          <label>
            WhatsApp display number
            <input
              className="input"
              name="wa_display_number"
              defaultValue={biz.wa_display_number ?? ""}
            />
          </label>
          <button className="btn" type="submit">
            Save
          </button>
        </form>
        {biz.call_link && (
          <p>
            Call link: <a href={biz.call_link}>{biz.call_link}</a>
          </p>
        )}
      </div>
    </main>
  );
}

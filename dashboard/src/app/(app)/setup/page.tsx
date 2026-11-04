import { api, sessionToken } from "@/lib/api";
import { get, Expired } from "@/lib/ui";
import { saveSetup } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Setup: owner edits business info; staff see it read-only (save 403s).
export default async function SetupPage({
  searchParams,
}: {
  searchParams: Promise<{ saved?: string }>;
}) {
  const { saved } = await searchParams;
  const biz = await api("/api/business", undefined, await sessionToken());
  return (
    <main>
      <div className="card">
        <h1>Setup</h1>
        {saved && <p>Saved.</p>}
        <form action={async (fd) => { await saveSetup(fd); }}>
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
      <StatusCard />
    </main>
  );
}

// Live WhatsApp connection + template approvals from Meta (cached 5 min).
async function StatusCard() {
  const d = await get("/api/templates");
  if (d.expired) return <Expired />;
  const items: any[] = d.data?.items ?? [];
  const find = (n: string) => items.find((t) => t.name === n);
  const qr = find("quote_request");
  const cp = find("call_permission");
  return (
    <div className="card">
      <h2>WhatsApp status</h2>
      {items.length === 0 && (
        <p>
          No token on the server, or no templates submitted yet. Stock checks
          and quote requests fall back to the invite link from your own
          WhatsApp until <em>quote_request</em> is approved; vendor calls wait
          on <em>call_permission</em>.
        </p>
      )}
      {qr && (
        <p>
          quote_request: <span className="pill">{qr.status}</span>
        </p>
      )}
      {cp && (
        <p>
          call_permission: <span className="pill">{cp.status}</span>
        </p>
      )}
    </div>
  );
}

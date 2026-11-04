import { get, Expired, PageHead } from "@/lib/ui";
import { addSeller, optOutSeller } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Only sellers the user added with the opt-in checkbox are ever messaged.
// STOP flips opted_in off immediately; the table shows the real state.
export default async function SellersPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  const d = await get("/api/sellers");
  if (d.expired) return <Expired />;
  const items: any[] = d.data?.items ?? [];
  return (
    <main>
      <PageHead
        title="Vendors"
        note="The agents message only vendors who agreed. Anyone else gets an invite link that you send from your own WhatsApp."
      />
      {error && <p className="notice">{error}</p>}
      <div className="split">
        <section>
          {items.length === 0 ? (
            <div className="empty">
              <h2>No vendors yet</h2>
              <p>Add a vendor who has agreed to hear from you, and the agents can ask them about stock, quotes and orders.</p>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="ledger">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>WhatsApp</th>
                    <th>Type</th>
                    <th>Messages</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((s) => (
                    <tr key={s.id}>
                      <td>{s.name || "—"}</td>
                      <td>{s.phone}</td>
                      <td className="muted">{s.kind === "vendor" ? "Construction" : "Shop"}</td>
                      <td>
                        {s.opted_in ? <span className="pill ok">Agreed</span> : <span className="pill bad">Opted out</span>}
                      </td>
                      <td>
                        {s.opted_in ? (
                          <form action={async (fd) => { "use server"; await optOutSeller(fd); }}>
                            <input type="hidden" name="id" value={s.id} />
                            <button className="link-danger" type="submit">
                              Opt out
                            </button>
                          </form>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section className="sheet">
          <h2>Add a vendor</h2>
          <form action={async (fd) => { "use server"; await addSeller(fd); }}>
            <label>
              Name
              <input className="input" name="name" maxLength={120} placeholder="Sharma Building Mart" />
            </label>
            <label>
              WhatsApp number <span className="norm">with country code</span>
              <input className="input" name="phone" required inputMode="tel" placeholder="+91…" />
            </label>
            <label>
              Type
              <select className="input" name="kind" defaultValue="shop">
                <option value="shop">Shop</option>
                <option value="vendor">Construction vendor</option>
              </select>
            </label>
            <label className="check">
              <input type="checkbox" name="agreed" required />
              <span>This vendor agreed to receive WhatsApp messages from us.</span>
            </label>
            <button className="btn" type="submit">
              Add vendor
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}

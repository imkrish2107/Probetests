import { get, Expired } from "@/lib/ui";
import { addSeller, optOutSeller } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Only sellers the user added with the opt-in checkbox are ever messaged.
// STOP flips opted_in off immediately; the table shows the real state.
export default async function SellersPage() {
  const d = await get("/api/sellers");
  if (d.expired) return <Expired />;
  const items = d.data?.items ?? [];
  return (
    <main>
      <div className="card">
        <h1>Sellers</h1>
        <p>
          We message only sellers you add here with the opt-in box ticked.
          Sellers you find on listings get an invite link from your own
          WhatsApp instead — never a message from us.
        </p>
        <table className="ledger">
          <thead>
            <tr>
              <th>Name</th>
              <th>Phone</th>
              <th>Kind</th>
              <th>Opted in</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((s: any) => (
              <tr key={s.id}>
                <td>{s.name || "—"}</td>
                <td>{s.phone}</td>
                <td>{s.kind}</td>
                <td>{s.opted_in ? <span className="pill ok">yes</span> : <span className="pill bad">no</span>}</td>
                <td>
                  {s.opted_in ? (
                    <form action={async (fd) => { await optOutSeller(fd); }}>
                      <input type="hidden" name="id" value={s.id} />
                      <button type="submit">Opt out</button>
                    </form>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && <p>No sellers yet.</p>}
      </div>

      <div className="card">
        <h2>Add a seller</h2>
        <form action={async (fd) => { await addSeller(fd); }}>
          <label>
            Name
            <input className="input" name="name" maxLength={120} />
          </label>
          <label>
            WhatsApp number <span className="norm">(digits, with country code)</span>
            <input className="input" name="phone" required inputMode="tel" />
          </label>
          <label>
            Kind
            <select className="input" name="kind" defaultValue="shop">
              <option value="shop">shop</option>
              <option value="vendor">vendor</option>
            </select>
          </label>
          <label>
            <input type="checkbox" name="agreed" required /> This seller agreed to
            receive WhatsApp messages from us.
          </label>
          <br />
          <br />
          <button className="btn" type="submit">
            Add seller
          </button>
        </form>
      </div>
    </main>
  );
}

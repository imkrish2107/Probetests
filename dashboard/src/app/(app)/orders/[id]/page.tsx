import { get, Expired, PageHead, Status, money, statusWord, when } from "@/lib/ui";
import { askForUpdate, cancelPurchase, markDelivered } from "@/lib/actions";
import Submit from "@/lib/submit";

export const dynamic = "force-dynamic";

// Order detail: status, delivery pick, courier/tracking/link, timeline of
// what each side said, Ask-for-update, Mark delivered, Cancel.
export default async function OrderPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ asked?: string; error?: string }>;
}) {
  const { id } = await params;
  const { asked, error } = await searchParams;
  const d = await get(`/api/purchases/${id}`);
  if (d.expired || !d.data?.id) return <Expired />;
  const p = d.data;
  const chaseable = ["seller_confirmed", "shipped"].includes(p.status) && !p.tracking_number;
  const open = !["delivered", "cancelled", "seller_declined"].includes(p.status);
  const canDeliver = ["seller_confirmed", "shipped"].includes(p.status);
  const safeLink = typeof p.tracking_link === "string" && p.tracking_link.startsWith("https://");
  return (
    <main>
      <PageHead
        crumb={{ href: "/orders", text: "All orders" }}
        title={`Order #${p.id}`}
        note={<Status value={p.status} />}
      >
        {chaseable && (
          <form action={async (fd) => { "use server"; await askForUpdate(fd); }}>
            <input type="hidden" name="id" value={p.id} />
            <Submit pending="Asking…">Ask for update</Submit>
          </form>
        )}
        {open && (
          <>
            {canDeliver && (
              <form action={async (fd) => { "use server"; await markDelivered(fd); }}>
                <input type="hidden" name="id" value={p.id} />
                <button className="btn ghost" type="submit">
                  Mark delivered
                </button>
              </form>
            )}
            <form action={async (fd) => { "use server"; await cancelPurchase(fd); }}>
              <input type="hidden" name="id" value={p.id} />
              <button className="btn danger" type="submit">
                Cancel order
              </button>
            </form>
          </>
        )}
      </PageHead>
      {asked && <p className="notice good">We asked the seller for an update.</p>}
      {error && <p className="notice">{error}</p>}
      {p.status === "draft" && (
        <p className="notice">
          This order hasn’t reached the seller yet. Cancel it and order again once the seller can be
          messaged.
        </p>
      )}
      <div className="split-even">
        <section>
          <h2 className="section-title">Details</h2>
          <table className="ledger facts">
            <tbody>
              <tr><th>Item</th><td>{p.item}</td></tr>
              <tr><th>Seller</th><td>{p.seller_name}</td></tr>
              <tr><th>Price</th><td>{money(p.price) ?? "Quote needed"}{p.unit ? ` / ${p.unit}` : ""}</td></tr>
              <tr>
                <th>Delivery</th>
                <td>
                  {p.delivery_option || "—"}
                  {p.delivery_reason && <span className="muted"> · Picker: {p.delivery_reason}</span>}
                </td>
              </tr>
              <tr>
                <th>Tracking</th>
                <td>
                  {[p.courier, p.tracking_number].filter(Boolean).join(" · ") || "Not shared yet"}
                  {safeLink && (
                    <>
                      {" · "}
                      <a href={p.tracking_link} target="_blank" rel="noreferrer">
                        Tracking page
                      </a>
                    </>
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </section>
        <section>
          <h2 className="section-title">Timeline</h2>
          <p className="muted small">What each side said, and when. Courier status is never guessed.</p>
          {(p.events ?? []).length === 0 ? (
            <p className="muted">Nothing yet.</p>
          ) : (
            <ul className="agents">
              {(p.events ?? []).map((e: any) => (
                <li key={e.id}>
                  <strong>{statusWord(e.status)}</strong>
                  <span className="muted small">{when(e.at)}</span>
                  {e.note && <p>{e.note}</p>}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  );
}

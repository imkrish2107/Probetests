import { get, Expired, PageHead, Empty, Status, money, when } from "@/lib/ui";

export const dynamic = "force-dynamic";

// Orders: everything the Buyer has sent, with the latest status from sellers.
export default async function OrdersPage() {
  const d = await get("/api/purchases");
  if (d.expired) return <Expired />;
  const items: any[] = d.data?.items ?? [];
  return (
    <main>
      <PageHead
        title="Orders"
        note="Orders you approved, and what each seller has said since. Payment stays between you and the seller."
      />
      {items.length === 0 ? (
        <Empty title="No orders yet" href="/hunts" cta="Start a hunt">
          When a hunt finds the right listing, click Order and approve the details. The order and its
          tracking will show up here.
        </Empty>
      ) : (
        <div className="table-wrap">
          <table className="ledger">
            <thead>
              <tr>
                <th>Order</th>
                <th>Item</th>
                <th>Seller</th>
                <th>Delivery</th>
                <th>Tracking</th>
                <th className="num">Price</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id}>
                  <td>
                    <a href={`/orders/${p.id}`}>#{p.id}</a>
                    <br />
                    <span className="muted small">{when(p.created_at)}</span>
                  </td>
                  <td>{p.item}</td>
                  <td>{p.seller_name}</td>
                  <td className="muted">{p.delivery_option || "—"}</td>
                  <td className="muted">{[p.courier, p.tracking_number].filter(Boolean).join(" · ") || "—"}</td>
                  <td className="num">{money(p.price) ?? "Quote"}</td>
                  <td>
                    <Status value={p.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}

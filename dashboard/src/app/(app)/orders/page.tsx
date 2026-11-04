import { get, Expired } from "@/lib/ui";

export const dynamic = "force-dynamic";

// Orders: list with status, delivery pick, courier/tracking and seller messages.
export default async function OrdersPage() {
  const d = await get("/api/purchases");
  if (d.expired) return <Expired />;
  const items = d.data?.items ?? [];
  return (
    <main>
      <div className="card">
        <h1>Orders</h1>
        {items.length === 0 && <p>No orders yet. Place one from a hunt listing.</p>}
        <table className="ledger">
          <thead>
            <tr>
              <th>Order</th>
              <th>Item</th>
              <th>Seller</th>
              <th>Price</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p: any) => (
              <tr key={p.id}>
                <td>
                  <a href={`/orders/${p.id}`}>#{p.id}</a>
                </td>
                <td>{p.item}</td>
                <td>{p.seller_name}</td>
                <td>{p.price ?? "Quote"}</td>
                <td>
                  <span className={`pill ${p.status === "delivered" ? "ok" : p.status === "needs_attention" || p.status === "seller_declined" ? "bad" : ""}`}>
                    {p.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}

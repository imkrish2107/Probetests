import { get, Expired } from "@/lib/ui";
import { createPurchase } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Place order: the confirmation screen. Item, seller, price, delivery with
// the Picker suggestion (changeable), name/address/phone from Setup, and the
// payment choice. Nothing is sent until Confirm. COD or pay-seller-directly
// only: money never moves through this app.
export default async function OrderConfirmPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; listing: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const { id, listing } = await params;
  const { error } = await searchParams;
  const h = await get(`/api/hunts/${id}`);
  if (h.expired || !h.data) return <Expired />;
  const l = (h.data.listings ?? []).find((x: any) => String(x.id) === String(listing));
  if (!l) return <p>Listing not found. <a href={`/hunts/${id}`}>Back to hunt</a></p>;
  const pk = await get(`/api/listings/${listing}/delivery-pick`);
  const biz = await get("/api/business");
  const b = biz.expired ? {} : biz.data ?? {};
  const pick = pk.expired ? null : pk.data;
  return (
    <main>
      <div className="card">
        <h1>Place order</h1>
        {error && <p className="pill bad">{error}</p>}
        <p>Check everything. The seller gets your name, address and phone only when you confirm.</p>
        <table className="ledger">
          <tbody>
            <tr><th>Item</th><td>{l.title || l.url}</td></tr>
            <tr><th>Seller</th><td>{l.seller || "—"}</td></tr>
            <tr><th>Price</th><td>{l.price ?? "Quote needed"}</td></tr>
            <tr>
              <th>Deliver to</th>
              <td>
                {[b.delivery_name, b.delivery_address, b.delivery_phone]
                  .filter(Boolean).join(", ") || "Set name, address and phone in Setup first."}
              </td>
            </tr>
          </tbody>
        </table>
        {pick?.reason && (
          <p className="muted">Picker suggests “{pick.pick?.label}”: {pick.reason}.</p>
        )}
        <form action={async (fd) => { "use server"; await createPurchase(fd); }}>
          <input type="hidden" name="listing_id" value={l.id} />
          <input type="hidden" name="hunt_id" value={id} />
          <input type="hidden" name="price" value={l.price ?? ""} />
          <input type="hidden" name="seller_id" value={l.seller_id ?? ""} />
          <label>
            Delivery
            <input
              className="input"
              name="delivery_option"
              defaultValue={pick?.pick?.label ?? l.delivery ?? ""}
              maxLength={200}
            />
          </label>
          <label>
            <input type="radio" name="payment" value="cod" defaultChecked /> Cash on
            delivery
          </label>
          <label>
            <input type="radio" name="payment" value="direct" /> Pay the seller
            directly
          </label>
          <br />
          <br />
          <button className="btn" type="submit">
            Confirm order
          </button>{" "}
          <a href={`/hunts/${id}`}>Cancel</a>
        </form>
      </div>
    </main>
  );
}

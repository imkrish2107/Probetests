import { get, Expired, PageHead, money } from "@/lib/ui";
import { createPurchase, linkSeller } from "@/lib/actions";
import Submit from "@/lib/submit";

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
  if (!l) {
    return (
      <main>
        <PageHead crumb={{ href: `/hunts/${id}`, text: "Back to hunt" }} title="Listing not found" />
      </main>
    );
  }
  const pk = await get(`/api/listings/${listing}/delivery-pick`);
  const biz = await get("/api/business");
  const sellers = await get("/api/sellers");
  const b = biz.expired ? {} : biz.data ?? {};
  const pick = pk.expired ? null : pk.data;
  const vendors = (sellers.expired ? [] : sellers.data?.items ?? []).filter((x: any) => x.opted_in);
  const hasAddress = Boolean(b.delivery_name && b.delivery_address && b.delivery_phone);
  const canOrder = hasAddress && Boolean(l.seller_id);
  return (
    <main>
      <PageHead
        crumb={{ href: `/hunts/${id}`, text: "Back to hunt" }}
        title="Check before you order"
        note="The seller gets your name, address and phone only when you confirm."
      />
      {error && <p className="notice">{error}</p>}
      <div className="split">
        <section>
          <table className="ledger facts">
            <tbody>
              <tr><th>Item</th><td>{l.title || l.url}</td></tr>
              <tr><th>Seller</th><td>{l.seller || "—"}</td></tr>
              <tr>
                <th>Price</th>
                <td>
                  {money(l.price, l.currency) ? <span className="price">{money(l.price, l.currency)}</span> : "Quote needed"}
                </td>
              </tr>
              <tr>
                <th>Deliver to</th>
                <td>
                  {hasAddress ? (
                    [b.delivery_name, b.delivery_address, b.delivery_phone].join(", ")
                  ) : (
                    <>Your delivery details are missing. <a href="/setup">Add them in Setup</a>.</>
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </section>
        <section className="sheet">
          {!l.seller_id ? (
            vendors.length > 0 ? (
              <form action={async (fd) => { "use server"; await linkSeller(fd); }}>
                <h2>Which vendor sells this?</h2>
                <p className="muted small">Only vendors who agreed to WhatsApp messages are listed.</p>
                <input type="hidden" name="hunt_id" value={id} />
                <input type="hidden" name="listing_id" value={l.id} />
                <input type="hidden" name="back" value={`/hunts/${id}/order/${l.id}`} />
                <select className="input" name="seller_id" aria-label="Vendor">
                  {vendors.map((v: any) => (
                    <option key={v.id} value={v.id}>
                      {v.name || v.phone}
                    </option>
                  ))}
                </select>
                <button className="btn" type="submit">
                  Use this vendor
                </button>
              </form>
            ) : (
              <>
                <h2>This seller isn’t set up yet</h2>
                <p className="muted">
                  We only message sellers who agreed. <a href="/sellers">Add this seller</a>, or
                  buy directly from <a href={l.url} target="_blank" rel="noreferrer">the listing</a>.
                </p>
              </>
            )
          ) : (
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
              {pick?.reason && (
                <p className="muted small">
                  Picker suggests “{pick.pick?.label}” because it’s {pick.reason}. You can change it.
                </p>
              )}
              <fieldset>
                <legend>Payment, directly to the seller</legend>
                <label className="check">
                  <input type="radio" name="payment" value="cod" defaultChecked />
                  <span>Cash on delivery</span>
                </label>
                <label className="check">
                  <input type="radio" name="payment" value="direct" />
                  <span>Pay the seller directly</span>
                </label>
              </fieldset>
              <Submit pending="Sending the order…" disabled={!canOrder}>
                Confirm order
              </Submit>
            </form>
          )}
        </section>
      </div>
    </main>
  );
}

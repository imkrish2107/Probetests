import { get, Expired } from "@/lib/ui";
import { askForUpdate, cancelPurchase, markDelivered } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Order detail: status, delivery pick, courier/tracking/link, timeline of
// what each side said, Ask-for-update, Mark delivered, Cancel.
export default async function OrderPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ asked?: string }>;
}) {
  const { id } = await params;
  const { asked } = await searchParams;
  const d = await get(`/api/purchases/${id}`);
  if (d.expired || !d.data?.id) return <Expired />;
  const p = d.data;
  const chaseable = ["seller_confirmed", "shipped"].includes(p.status) && !p.tracking_number;
  const open = !["delivered", "cancelled", "seller_declined"].includes(p.status);
  return (
    <main>
      <div className="card">
        <h1>
          Order #{p.id} <span className="pill">{p.status}</span>
        </h1>
        {asked && <p>Update asked.</p>}
        <p>
          {p.item} — {p.price ?? "Quote"} {p.unit} from {p.seller_name}
        </p>
        <p>
          Delivery: {p.delivery_option || "—"}
          {p.delivery_reason && <span className="muted"> ({p.delivery_reason})</span>}
        </p>
        {(p.courier || p.tracking_number || p.tracking_link) && (
          <p>
            {[p.courier, p.tracking_number].filter(Boolean).join(" · ")}
            {p.tracking_link && (
              <>
                {" · "}
                <a href={p.tracking_link} target="_blank" rel="noreferrer">
                  Tracking page
                </a>
              </>
            )}
          </p>
        )}
        {chaseable && (
          <form action={async (fd) => { await askForUpdate(fd); }}>
            <input type="hidden" name="id" value={p.id} />
            <button className="btn" type="submit">
              Ask for update
            </button>
          </form>
        )}
        {open && (
          <>
            <form action={async (fd) => { await markDelivered(fd); }}>
              <input type="hidden" name="id" value={p.id} />
              <button className="btn" type="submit">
                Mark delivered
              </button>
            </form>{" "}
            <form action={async (fd) => { await cancelPurchase(fd); }}>
              <input type="hidden" name="id" value={p.id} />
              <button className="btn danger" type="submit">
                Cancel order
              </button>
            </form>
          </>
        )}
      </div>

      <div className="card">
        <h2>Timeline</h2>
        <p className="muted">Who said what, and when. Courier status is never guessed.</p>
        <ul className="steps">
          {(p.events ?? []).map((e: any) => (
            <li key={e.id}>
              <strong>{e.status}</strong> {e.note} <span className="muted">{e.at}</span>
            </li>
          ))}
        </ul>
        {(p.events ?? []).length === 0 && <p>No events yet.</p>}
      </div>
    </main>
  );
}

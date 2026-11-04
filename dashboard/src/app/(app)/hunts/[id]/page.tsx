import { get, Expired } from "@/lib/ui";
import { api, sessionToken } from "@/lib/api";
import Refresh from "./refresh";
import {
  approveHunt,
  buildBoq,
  confirmRooms,
  deleteHunt,
  editBoqQty,
  genImage,
  startVendorSearch,
  stockCheck,
} from "@/lib/actions";

export const dynamic = "force-dynamic";

// One hunt. Shopping: photo, Spotter result, listings, top pick, cost.
// Construction: Plan check -> BOQ -> House image -> Approve -> Vendors ->
// Calls -> Compare. Only reachable steps are active; each shows real state.
export default async function HuntPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ preview?: string; error?: string }>;
}) {
  const { id } = await params;
  const { preview, error } = await searchParams;
  const d = await get(`/api/hunts/${id}`);
  if (d.expired || !d.data) return <Expired />;
  const { hunt, steps, listings, rooms } = d.data;
  const construction = hunt.flow === "construction";
  let vendors: any = null;
  let approval: any = null;
  if (construction) {
    const v = await get(`/api/hunts/${id}/vendors`);
    if (!v.expired) vendors = v.data;
    const a = await get(`/api/hunts/${id}/approval`);
    if (!a.expired) approval = a;
  }
  return (
    <main>
      <Refresh active={hunt.status === "running"} />
      <div className="card">
        <h1>
          #{hunt.id} {construction ? "House" : "Product"} hunt
        </h1>
        <p>
          <span className="pill">{hunt.status}</span>{" "}
          <span className="muted">
            {hunt.searches_used} searches · ${Number(hunt.cost_usd).toFixed(4)}
          </span>
        </p>
        {hunt.error && <p className="pill bad">{hunt.error}</p>}
        {error && <p className="pill bad">{error}</p>}
        {hunt.top_reason && <p>{hunt.top_reason}</p>}
        <form action={async (fd) => { "use server"; await deleteHunt(fd); }}>
          <input type="hidden" name="id" value={hunt.id} />
          <button className="btn danger" type="submit">
            Delete hunt
          </button>
        </form>
      </div>

      <div className="card">
        <h2>Agents</h2>
        {steps.length === 0 && <p>Not started.</p>}
        <ul className="steps">
          {steps.map((s: any, i: number) => (
            <li key={i}>
              <strong>{s.agent}</strong>{" "}
              <span className={`pill ${s.state === "done" ? "ok" : s.state === "failed" ? "bad" : ""}`}>
                {s.state}
              </span>{" "}
              {s.detail} <span className="muted">{s.at}</span>
            </li>
          ))}
        </ul>
      </div>

      {!construction && (
        <Shopping hunt={hunt} listings={listings} previewId={preview} />
      )}
      {construction && (
        <Construction
          hunt={hunt}
          rooms={rooms}
          vendors={vendors}
          approval={approval}
        />
      )}
    </main>
  );
}

function Shopping({ hunt, listings, previewId }: { hunt: any; listings: any[]; previewId?: string }) {
  let spot: any = {};
  try {
    spot = JSON.parse(hunt.spot || "{}");
  } catch {
    spot = {};
  }
  return (
    <>
      <div className="card">
        <h2>Photo</h2>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="shot" src={`/hunts/${hunt.id}/photo`} alt="hunt photo" />
        {(spot.colour || spot.garment) && (
          <p>
            Spotter saw: {spot.colour} {spot.garment}
            {spot.pattern ? `, ${spot.pattern}` : ""}
            {spot.fabric ? `, ${spot.fabric}` : ""}
          </p>
        )}
      </div>
      <div className="card">
        <h2>Listings</h2>
        {listings.length === 0 && <p>No listings yet.</p>}
        <table className="ledger">
          <thead>
            <tr>
              <th>Title</th>
              <th>Seller</th>
              <th>Price</th>
              <th>Stock</th>
              <th>Match</th>
              <th>Verified</th>
              <th>Ask</th>
            </tr>
          </thead>
          <tbody>
            {listings.map((l: any) => (
              <tr key={l.id}>
                <td>
                  <a href={l.url} target="_blank" rel="noreferrer">
                    {l.title || l.url}
                  </a>
                  <br />
                  <span className="muted">{l.delivery}</span>
                </td>
                <td>{l.seller}</td>
                <td>{l.price ?? "Quote needed"}</td>
                <td>{l.in_stock}</td>
                <td>{l.similarity}</td>
                <td>{l.verified ? <span className="pill ok">verified</span> : "not verified"}</td>
                <td>
                  <a href={`/hunts/${hunt.id}?preview=${l.id}`}>Ask seller</a>
                  <br />
                  <a href={`/hunts/${hunt.id}/order/${l.id}`}>Place order</a>
                  {l.whatsapp && (
                    <>
                      <br />
                      <a href={`/hunts/${hunt.id}/invite/${l.id}`}>Ask from my WhatsApp</a>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {previewId && <PreviewBox huntId={hunt.id} listingId={previewId} listings={listings} />}
      </div>
    </>
  );
}

async function PreviewBox({
  huntId,
  listingId,
  listings,
}: {
  huntId: number;
  listingId: string;
  listings: any[];
}) {
  const l = listings.find((x: any) => String(x.id) === String(listingId));
  let text = "Could not load the preview.";
  try {
    const r = await api(
      `/api/listings/${listingId}/stock-check`,
      {
        method: "POST",
        body: JSON.stringify({ seller_id: l?.seller_id ?? null, preview: true }),
      },
      await sessionToken(),
    );
    text = r?.preview ?? r?.note ?? text;
  } catch {
    // text already says it failed
  }
  return (
    <div className="card">
      <h2>Ask seller</h2>
      <p>The exact message:</p>
      <p>
        <em>{text}</em>
      </p>
      <form action={async (fd) => { "use server"; await stockCheck(fd); }}>
        <input type="hidden" name="hunt_id" value={huntId} />
        <input type="hidden" name="listing_id" value={listingId} />
        <input type="hidden" name="seller_id" value={l?.seller_id ?? ""} />
        <input type="hidden" name="send" value="1" />
        <button className="btn" type="submit">
          Send
        </button>{" "}
        <a href={`/hunts/${huntId}`}>Cancel</a>
      </form>
    </div>
  );
}

function Construction({
  hunt,
  rooms,
  vendors,
  approval,
}: {
  hunt: any;
  rooms: any[];
  vendors: any;
  approval: any;
}) {
  const roomRows = rooms.filter((r: any) => r.status === "room");
  const boqRows = rooms.filter((r: any) => r.status === "boq");
  const awaiting = hunt.status === "awaiting_rooms" || hunt.status === "running";
  return (
    <>
      <div className="card">
        <h2>1. Plan check</h2>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="plan" src={`/hunts/${hunt.id}/photo`} alt="floor plan" />
        {awaiting && <p>Reading the plan… this page refreshes every 3 seconds.</p>}
        {roomRows.length > 0 && (
          <form action={async (fd) => { "use server"; await confirmRooms(fd); }}>
            <input type="hidden" name="id" value={hunt.id} />
            <input type="hidden" name="count" value={roomRows.length} />
            <table className="ledger">
              <thead>
                <tr>
                  <th>Room</th>
                  <th>Length</th>
                  <th>Width</th>
                </tr>
              </thead>
              <tbody>
                {roomRows.map((r: any, i: number) => {
                  let spec: any = {};
                  try {
                    spec = JSON.parse(r.spec || "{}");
                  } catch {
                    spec = {};
                  }
                  return (
                    <tr key={r.id}>
                      <td>
                        <input className="input" name={`name-${i}`} defaultValue={r.name} />
                        <input type="hidden" name={`unit-${i}`} value={spec.unit || r.unit || "ft"} />
                      </td>
                      <td>
                        <input
                          className="input"
                          name={`length-${i}`}
                          type="number"
                          step="any"
                          defaultValue={spec.length ?? ""}
                        />
                      </td>
                      <td>
                        <input
                          className="input"
                          name={`width-${i}`}
                          type="number"
                          step="any"
                          defaultValue={spec.width ?? ""}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <button className="btn" type="submit">
              Confirm rooms
            </button>
          </form>
        )}
      </div>

      <div className="card">
        <h2>2. BOQ</h2>
        {boqRows.length === 0 && (
          <form action={async (fd) => { "use server"; await buildBoq(fd); }}>
            <input type="hidden" name="id" value={hunt.id} />
            <button className="btn" type="submit" disabled={hunt.status !== "rooms_confirmed"}>
              Build BOQ
            </button>
          </form>
        )}
        {boqRows.length > 0 && (
          <>
            <p className="warning">
              Estimate from thumb rules. Have a civil engineer check it before buying or building.
              This is not a structural design. Editing a row clears the approval below.
            </p>
            <table className="ledger">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Qty</th>
                  <th>Range</th>
                  <th>Basis</th>
                  <th>Edit</th>
                </tr>
              </thead>
              <tbody>
                {boqRows.map((r: any) => {
                  let spec: any = {};
                  try {
                    spec = JSON.parse(r.spec || "{}");
                  } catch {
                    spec = {};
                  }
                  return (
                    <tr key={r.id}>
                      <td>{r.name}</td>
                      <td>
                        {r.quantity} {r.unit}
                      </td>
                      <td>{spec.range}</td>
                      <td>{spec.basis}</td>
                      <td>
                        <form action={async (fd) => { "use server"; await editBoqQty(fd); }}>
                          <input type="hidden" name="id" value={hunt.id} />
                          <input type="hidden" name="name" value={r.name} />
                          <input
                            className="input"
                            name="quantity"
                            type="number"
                            step="any"
                            defaultValue={r.quantity}
                            style={{ width: "5em", display: "inline" }}
                          />{" "}
                          <button type="submit">Set</button>
                        </form>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p>
              <a href={`/hunts/${hunt.id}/boq.csv`}>Download CSV</a>
            </p>
          </>
        )}
      </div>

      <div className="card">
        <h2>3. House image</h2>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="shot" src={`/hunts/${hunt.id}/image?n=1`} alt="concept house" />
        <p className="muted">Concept image. Not to scale, and the real building will differ.</p>
        <form action={async (fd) => { "use server"; await genImage(fd); }}>
          <input type="hidden" name="id" value={hunt.id} />
          <label>
            Style note <span className="norm">(optional)</span>
            <input className="input" name="style" maxLength={200} />
          </label>
          <button className="btn" type="submit">
            Generate image
          </button>
        </form>
      </div>

      <div className="card">
        <h2>4. Approve</h2>
        {approval?.data?.approved ? (
          <p>
            <span className="pill ok">approved</span> {approval.data.approved_at}
          </p>
        ) : (
          <>
            <p>{approval?.data?.reason ?? "Build the BOQ first."}</p>
            {boqRows.length > 0 && (
              <form action={async (fd) => { "use server"; await approveHunt(fd); }}>
                <input type="hidden" name="id" value={hunt.id} />
                <input type="hidden" name="image" value={`${hunt.id}_concept_1.jpg`} />
                <button className="btn" type="submit">
                  Approve BOQ + image
                </button>
              </form>
            )}
          </>
        )}
      </div>

      <div className="card">
        <h2>5. Vendors</h2>
        {boqRows.length > 0 && (
          <form action={async (fd) => { "use server"; await startVendorSearch(fd); }}>
            <input type="hidden" name="id" value={hunt.id} />
            {boqRows.map((r: any) => (
              <label key={r.id}>
                <input type="checkbox" name="item" value={r.id} defaultChecked /> {r.name} (
                {r.quantity} {r.unit})
              </label>
            ))}
            <br />
            <br />
            <button className="btn" type="submit">
              Search vendors
            </button>
          </form>
        )}
        {vendors?.items?.map((g: any) => (
          <div key={g.item}>
            <h3>
              {g.item} — {g.priced} priced, {g.blocked} blocked
            </h3>
            <table className="ledger">
              <thead>
                <tr>
                  <th>Vendor</th>
                  <th>Price</th>
                  <th>Delivery</th>
                  <th>Flags</th>
                  <th>Contact</th>
                </tr>
              </thead>
              <tbody>
                {g.listings.map((l: any) => (
                  <tr key={l.id}>
                    <td>
                      {l.seller || "unknown"}
                      <br />
                      <span className="muted">{l.city}</span>
                    </td>
                    <td>{l.price != null ? `${l.price} / ${l.unit}` : "Quote needed"}</td>
                    <td>{l.delivery || l.in_stock}</td>
                    <td>
                      {l.is_best && <span className="pill ok">best</span>}{" "}
                      {l.is_cheapest && <span className="pill">cheapest</span>}{" "}
                      {l.verified ? "verified" : "not verified"}
                    </td>
                    <td>
                      <a href={l.url} target="_blank" rel="noreferrer">
                        Open
                      </a>
                      <br />
                      {l.seller_opted_in ? (
                        <a href={`tel:${l.url}`}>Call</a>
                      ) : (
                        <a href={`/hunts/${hunt.id}/invite/${l.id}`}>Invite from my WhatsApp</a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {g.best_reason && <p className="muted">{g.best_reason}</p>}
          </div>
        ))}
      </div>

      <div className="card">
        <h2>6. Calls</h2>
        <p>
          AI vendor calling lands after the phone test passes. Until then, send a{" "}
          <em>quote request</em> on WhatsApp or call the vendor yourself from the
          Vendors table above.
        </p>
      </div>

      <Compare hunt={hunt} vendors={vendors} />
    </>
  );
}

function Compare({ hunt, vendors }: { hunt: any; vendors: any }) {
  if (!vendors?.items?.length) return null;
  const quoted = vendors.items.filter((g: any) =>
    g.listings.some((l: any) => l.price != null && l.verified),
  ).length;
  const total = vendors.items.length;
  return (
    <div className="card">
      <h2>7. Compare</h2>
      <p>
        {quoted} of {total} items have a verified quote
        {quoted < total && ` — ${total - quoted} still none`}.
      </p>
      <table className="ledger">
        <thead>
          <tr>
            <th>Item</th>
            <th>Best</th>
            <th>Cheapest</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {vendors.items.map((g: any) => {
            const best = g.listings.find((l: any) => l.is_best);
            const cheap = g.listings.find((l: any) => l.is_cheapest);
            return (
              <tr key={g.item}>
                <td>
                  {g.item} ({g.quantity} {g.unit})
                </td>
                <td>{best ? `${best.seller}: ${best.price} / ${best.unit}` : "—"}</td>
                <td>{cheap ? `${cheap.seller}: ${cheap.price} / ${cheap.unit}` : "—"}</td>
                <td>
                  {best && (
                    <a href={best.url} target="_blank" rel="noreferrer">
                      Open listing
                    </a>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

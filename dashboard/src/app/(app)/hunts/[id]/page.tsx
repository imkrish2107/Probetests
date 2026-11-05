import { get, Expired, PageHead, Status, money, plainError, stepNote, when } from "@/lib/ui";
import { api, sessionToken } from "@/lib/api";
import Submit from "@/lib/submit";
import Refresh from "./refresh";
import {
  approveHunt,
  buildBoq,
  confirmRooms,
  deleteHunt,
  editBoqQty,
  genImage,
  linkSeller,
  quoteRequest,
  readPlanAgain,
  startVendorSearch,
  stockCheck,
} from "@/lib/actions";

export const dynamic = "force-dynamic";

// One hunt. Shopping: photo, what Spotter saw, ranked listings, ask and order.
// Construction: Plan check -> BOQ -> House image -> Approve -> Vendors ->
// Quotes -> Compare. Only reachable steps are active; each shows real state.
export default async function HuntPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ preview?: string; quote?: string; sent?: string; error?: string }>;
}) {
  const { id } = await params;
  const { preview, quote, sent, error } = await searchParams;
  const d = await get(`/api/hunts/${id}`);
  if (d.expired || !d.data) return <Expired />;
  const { hunt, steps, listings, rooms, images } = d.data;
  const construction = hunt.flow === "construction";
  let vendors: any = null;
  let approval: any = null;
  if (construction) {
    const v = await get(`/api/hunts/${id}/vendors`);
    if (!v.expired) vendors = v.data;
    const a = await get(`/api/hunts/${id}/approval`);
    if (!a.expired) approval = a.data;
  }
  const running = hunt.status === "running";
  const hasActivity = construction && (vendors?.items ?? []).some((g: any) => g.listings.length > 0);
  return (
    <main>
      <Refresh active={running} />
      <PageHead
        crumb={{ href: "/hunts", text: "All hunts" }}
        title={`${construction ? "House plan" : "Product hunt"} #${hunt.id}`}
        note={
          <>
            <Status value={hunt.status} /> · {when(hunt.created_at)} · {hunt.searches_used} searches · $
            {Number(hunt.cost_usd).toFixed(3)}
          </>
        }
      >
        <form action={async (fd) => { "use server"; await deleteHunt(fd); }}>
          <input type="hidden" name="id" value={hunt.id} />
          <button className="link-danger" type="submit">
            Delete hunt
          </button>
        </form>
      </PageHead>
      {error && <p className="notice">{error}</p>}
      {sent && <p className="notice good">{sent}</p>}
      {hunt.error && !(construction && hunt.status === "failed") && <p className="notice">{plainError(hunt.error)}</p>}
      {hunt.error && (
        <details className="small" style={{ marginBottom: 18 }}>
          <summary>Technical detail</summary>
          <p className="muted">{hunt.error}</p>
        </details>
      )}
      {!construction && (
        <Shopping hunt={hunt} steps={steps} listings={listings} previewId={preview} />
      )}
      {construction && (
        <Construction
          hunt={hunt}
          rooms={rooms}
          images={images ?? []}
          vendors={vendors}
          approval={approval}
          steps={steps}
          quoteId={quote}
          hasListings={hasActivity}
        />
      )}
    </main>
  );
}

function Activity({ steps }: { steps: any[] }) {
  if (steps.length === 0) return <p className="muted">The agents have not started yet.</p>;
  return (
    <ul className="agents">
      {steps.filter((s) => s.state !== "queued").slice(-8).map((s: any, i: number) => (
        <li key={i}>
          <strong>{s.agent}</strong>
          <Status value={s.state} />
          <p>
            {stepNote(s)} {stepNote(s) && "· "}
            {when(s.at)}
          </p>
        </li>
      ))}
    </ul>
  );
}

function rankListings(listings: any[]) {
  return [...listings].sort((a, b) => {
    const score = (l: any) => [
      l.verified ? 0 : 1,
      l.in_stock === "no" ? 1 : 0,
      l.price == null ? 1 : 0,
      Number(l.price ?? 0),
    ];
    const x = score(a);
    const y = score(b);
    for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] - y[i];
    return 0;
  });
}

function stockWord(v?: string) {
  if (v === "yes") return "In stock";
  if (v === "no") return "Out of stock";
  return "Stock not checked";
}

function Shopping({
  hunt,
  steps,
  listings,
  previewId,
}: {
  hunt: any;
  steps: any[];
  listings: any[];
  previewId?: string;
}) {
  let spot: any = {};
  try {
    spot = JSON.parse(hunt.spot || "{}");
  } catch {
    spot = {};
  }
  const seen = [spot.colour, spot.pattern, spot.fabric, spot.garment].filter(Boolean).join(" ");
  const ranked = rankListings(listings);
  const top = ranked[0]?.verified && ranked[0]?.price != null ? ranked[0] : null;
  return (
    <>
      <div className="split card">
        <section>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="plan-view" src={`/hunts/${hunt.id}/photo`} alt="The photo you uploaded" />
          {seen && (
            <p style={{ marginTop: 12 }}>
              <strong>Spotter saw:</strong> {seen}
            </p>
          )}
        </section>
        <section>
          <h2 className="section-title">What the agents did</h2>
          <Activity steps={steps} />
        </section>
      </div>
      {top && (
        <section className="sheet" style={{ marginBottom: 30 }}>
          <span className="pill ok">Top pick</span>
          <h2 style={{ margin: "10px 0 4px" }}>{top.title}</h2>
          <p>
            <span className="price">{money(top.price, top.currency)}</span> from {top.seller || "this seller"}
          </p>
          <p className="muted">{hunt.top_reason}</p>
          <div className="actions">
            <a className="btn" href={`/hunts/${hunt.id}/order/${top.id}`}>
              Place order
            </a>
            <a className="btn ghost" href={`/hunts/${hunt.id}?preview=${top.id}#ask`}>
              Ask seller first
            </a>
          </div>
        </section>
      )}
      {previewId && <AskStock huntId={hunt.id} listingId={previewId} listings={listings} />}
      <section className="card">
        <h2 className="section-title">Listings checked</h2>
        {ranked.length === 0 ? (
          <p className="muted">
            {hunt.status === "running"
              ? "The agents are still looking. This page updates by itself."
              : "No listings found for this photo."}
          </p>
        ) : (
          <div className="table-wrap">
            <table className="ledger">
              <thead>
                <tr>
                  <th>Listing</th>
                  <th>Price</th>
                  <th>Stock</th>
                  <th>Match</th>
                  <th>Checked</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {ranked.map((l: any) => (
                  <tr key={l.id} className={top?.id === l.id ? "top" : ""}>
                    <td>
                      <div className="listing">
                        {l.image_url?.startsWith("https://") && (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img className="thumb" src={l.image_url} alt="" referrerPolicy="no-referrer" loading="lazy" />
                        )}
                        <div>
                          <a href={l.url} target="_blank" rel="noreferrer">
                            {l.title || "Open listing"}
                          </a>
                          <br />
                          <span className="muted small">
                            {[l.seller, l.delivery].filter(Boolean).join(" · ")}
                          </span>
                        </div>
                      </div>
                    </td>
                    <td className="price">{money(l.price, l.currency) ?? <span className="muted small">Not verified</span>}</td>
                    <td>{stockWord(l.in_stock)}</td>
                    <td>{l.similarity != null ? `${l.similarity}%` : "—"}</td>
                    <td>
                      {l.verified ? <span className="pill ok">Verified</span> : <span className="pill">Not verified</span>}
                    </td>
                    <td>
                      <div className="actions">
                        <a className="btn small" href={`/hunts/${hunt.id}/order/${l.id}`}>
                          Order
                        </a>
                        <a className="btn ghost small" href={`/hunts/${hunt.id}?preview=${l.id}#ask`}>
                          Ask
                        </a>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

async function VendorPicker({ huntId, listingId }: { huntId: number; listingId: string | number }) {
  const s = await get("/api/sellers");
  const items = (s.expired ? [] : s.data?.items ?? []).filter((x: any) => x.opted_in);
  if (items.length === 0) {
    return (
      <p>
        No vendors have agreed to messages yet. <a href="/sellers">Add a vendor</a> first.
      </p>
    );
  }
  return (
    <form action={async (fd) => { "use server"; await linkSeller(fd); }} className="actions">
      <input type="hidden" name="hunt_id" value={huntId} />
      <input type="hidden" name="listing_id" value={listingId} />
      <label>
        Which vendor sells this?
        <select className="input" name="seller_id" style={{ marginBottom: 0 }}>
          {items.map((x: any) => (
            <option key={x.id} value={x.id}>
              {x.name || x.phone}
            </option>
          ))}
        </select>
      </label>
      <button className="btn ghost" type="submit" style={{ alignSelf: "flex-end" }}>
        Use this vendor
      </button>
    </form>
  );
}

async function previewText(path: string, body: object) {
  try {
    return await api(path, { method: "POST", body: JSON.stringify({ ...body, preview: true }) }, await sessionToken());
  } catch {
    return { note: "Could not load the message." };
  }
}

async function AskStock({ huntId, listingId, listings }: { huntId: number; listingId: string; listings: any[] }) {
  const l = listings.find((x: any) => String(x.id) === String(listingId));
  const r = await previewText(`/api/listings/${listingId}/stock-check`, { seller_id: l?.seller_id ?? null });
  return (
    <section className="sheet" id="ask" style={{ marginBottom: 30 }}>
      <h2>Ask the seller</h2>
      {r?.preview ? (
        <>
          <p className="muted">The exact WhatsApp message that will be sent:</p>
          <p><em>{r.preview}</em></p>
          <form action={async (fd) => { "use server"; await stockCheck(fd); }} className="actions">
            <input type="hidden" name="hunt_id" value={huntId} />
            <input type="hidden" name="listing_id" value={listingId} />
            <input type="hidden" name="seller_id" value={l?.seller_id ?? ""} />
            <input type="hidden" name="send" value="1" />
            <Submit pending="Sending…">Send on WhatsApp</Submit>
            <a href={`/hunts/${huntId}`}>Cancel</a>
          </form>
        </>
      ) : (
        <>
          <VendorPicker huntId={huntId} listingId={listingId} />
          {l?.whatsapp && (
            <p style={{ marginTop: 12 }}>
              Or <a href={`/hunts/${huntId}/invite/${listingId}`}>invite them from your own WhatsApp</a>.
            </p>
          )}
          <p style={{ marginTop: 12 }}>
            <a href={`/hunts/${huntId}`}>Cancel</a>
          </p>
        </>
      )}
    </section>
  );
}

function jsonOf(s?: string) {
  try {
    return JSON.parse(s || "{}");
  } catch {
    return {};
  }
}

function Construction({
  hunt,
  rooms,
  images,
  vendors,
  approval,
  steps,
  quoteId,
  hasListings,
}: {
  hunt: any;
  rooms: any[];
  images: string[];
  vendors: any;
  approval: any;
  steps: any[];
  quoteId?: string;
  hasListings: boolean;
}) {
  const roomRows = rooms.filter((r: any) => r.status === "room");
  const boqRows = rooms.filter((r: any) => r.status === "boq");
  const reading = hunt.status === "running";
  const needRooms = hunt.status === "awaiting_rooms" || hunt.status === "failed";
  const roomsDone = ["rooms_confirmed", "boq_ready", "approved"].includes(hunt.status) || boqRows.length > 0;
  const approved = Boolean(approval?.approved);
  const quoted = (vendors?.items ?? []).some((g: any) =>
    g.listings.some((l: any) => l.price != null),
  );
  const stages = [
    { key: "plan", name: "Plan check", done: roomsDone },
    { key: "boq", name: "BOQ", done: boqRows.length > 0 },
    { key: "image", name: "3D render", done: images.length > 0 },
    { key: "approve", name: "Approve", done: approved },
    { key: "vendors", name: "Vendors", done: hasListings },
    { key: "quotes", name: "Quotes", done: quoted },
    { key: "compare", name: "Compare", done: false },
  ];
  const now = stages.find((s) => !s.done)?.key ?? "compare";
  const intake = jsonOf(hunt.spot);
  return (
    <>
      <ol className="stepper" aria-label="Progress">
        {stages.map((s) => (
          <li key={s.key} className={s.key === now ? "now" : s.done ? "done" : ""} aria-current={s.key === now ? "step" : undefined}>
            <a href={`#${s.key}`}>{s.name}</a>
          </li>
        ))}
      </ol>

      <section className="card" id="plan">
        <div className="split-even">
          <div>
            <h2 className="section-title">Check the rooms</h2>
            {reading && <p className="notice">The Plan Reader is working. This page updates by itself.</p>}
            {needRooms && roomRows.length === 0 && (
              <>
                <p className="notice">
                  {hunt.error === "server restarted"
                    ? "The server restarted before the Plan Reader could finish."
                    : hunt.status === "failed"
                      ? "The Plan Reader couldn’t finish this plan."
                      : "The Plan Reader found no rooms on this plan."}{" "}
                  Read it again, or enter the rooms yourself.
                </p>
                <form action={async (fd) => { "use server"; await readPlanAgain(fd); }} style={{ marginBottom: 18 }}>
                  <input type="hidden" name="id" value={hunt.id} />
                  <Submit pending="Starting…">Read the plan again</Submit>
                </form>
                <RoomForm huntId={hunt.id} rows={[]} blank={8} action="Save rooms" />
              </>
            )}
            {roomRows.length > 0 && needRooms && (
              <>
                <p className="muted">Check every size against your plan. Nothing is calculated until you confirm.</p>
                <RoomForm huntId={hunt.id} rows={roomRows} blank={2} action="Confirm rooms" />
              </>
            )}
            {hunt.status === "rooms_confirmed" && roomRows.length > 0 && (
              <details>
                <summary>{roomRows.length} rooms confirmed. Edit</summary>
                <RoomForm huntId={hunt.id} rows={roomRows} blank={1} action="Save rooms" />
              </details>
            )}
            {boqRows.length > 0 && roomRows.length > 0 && (
              <p>
                <span className="pill ok">Confirmed</span>{" "}
                {roomRows
                  .map((r: any) => {
                    const s = jsonOf(r.spec);
                    return `${r.name} ${s.length ?? "?"} × ${s.width ?? "?"} ft`;
                  })
                  .join(", ")}
              </p>
            )}
            <p className="muted small" style={{ marginTop: 12 }}>
              {[intake.city, intake.floors && `${intake.floors} floor${intake.floors > 1 ? "s" : ""}`, intake.finish && `${intake.finish} finish`]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
          <div>
            {hunt.plan_is_pdf ? (
              <object className="plan-view" type="application/pdf" data={`/hunts/${hunt.id}/photo`} aria-label="Your floor plan">
                <a href={`/hunts/${hunt.id}/photo`}>Open your floor plan</a>
              </object>
            ) : (
              // eslint-disable-next-line @next/next/no-img-element
              <img className="plan-view" src={`/hunts/${hunt.id}/photo`} alt="Your floor plan" />
            )}
          </div>
        </div>
      </section>

      <section className="card" id="boq">
        <div className="section-head">
          <h2>Bill of quantities</h2>
          {boqRows.length > 0 && (
            <a className="small" href={`/hunts/${hunt.id}/boq.csv`}>
              Download CSV
            </a>
          )}
        </div>
        {boqRows.length === 0 ? (
          hunt.status === "rooms_confirmed" ? (
            <form action={async (fd) => { "use server"; await buildBoq(fd); }}>
              <input type="hidden" name="id" value={hunt.id} />
              <Submit pending="Calculating…">Build the BOQ</Submit>
            </form>
          ) : (
            <p className="locked">Confirm the rooms first.</p>
          )
        ) : (
          <>
            <p className="warning">
              Estimate from thumb rules. Have a civil engineer check it before buying or building.
              This is not a structural design.
            </p>
            <div className="table-wrap">
              <table className="ledger">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th className="num">Quantity</th>
                    <th>Range</th>
                    <th>How it was worked out</th>
                    <th>Change</th>
                  </tr>
                </thead>
                <tbody>
                  {boqRows.map((r: any) => {
                    const spec = jsonOf(r.spec);
                    return (
                      <tr key={r.id}>
                        <td><strong>{r.name}</strong></td>
                        <td className="num">
                          {r.quantity} {r.unit}
                        </td>
                        <td className="muted small">{spec.range}</td>
                        <td className="muted small">{spec.basis}</td>
                        <td>
                          <form action={async (fd) => { "use server"; await editBoqQty(fd); }} className="actions" style={{ flexWrap: "nowrap" }}>
                            <input type="hidden" name="id" value={hunt.id} />
                            <input type="hidden" name="name" value={r.name} />
                            <input
                              className="input"
                              name="quantity"
                              type="number"
                              step="any"
                              min={0}
                              defaultValue={r.quantity}
                              aria-label={`New quantity for ${r.name}`}
                              style={{ width: "6.5em" }}
                            />
                            <button className="btn ghost small" type="submit">
                              Set
                            </button>
                          </form>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section className="card" id="image">
        <h2 className="section-title">3D interior render</h2>
        {boqRows.length === 0 ? (
          <p className="locked">Build the BOQ first.</p>
        ) : (
          <div className="split">
            <div>
              {images.length === 0 ? (
                <p className="muted">No render yet. The House Artist builds a cutaway 3D view from your plan and confirmed rooms.</p>
              ) : (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  className="figure"
                  src={`/hunts/${hunt.id}/image?n=${imageNum(images[images.length - 1])}`}
                  alt="3D concept render of the rooms from your floor plan"
                />
              )}
              <p className="muted small" style={{ marginTop: 8 }}>
                Concept render. Furniture and finishes are illustrative, and it is not to scale.
              </p>
            </div>
            <form action={async (fd) => { "use server"; await genImage(fd); }}>
              <input type="hidden" name="id" value={hunt.id} />
              <label>
                Style note <span className="norm">optional</span>
                <input className="input" name="style" maxLength={200} placeholder="Warm wood, white walls, modern furniture" />
              </label>
              <Submit pending="Rendering, this can take a few minutes…" className={images.length ? "btn ghost" : "btn"} disabled={images.length >= 5 || hunt.plan_is_pdf}>
                {images.length ? "Render another" : "Create the 3D render"}
              </Submit>
              <p className="muted small" style={{ marginTop: 8 }}>
                {images.length} of 5 renders used
              </p>
              {hunt.plan_is_pdf && (
                <p className="notice" style={{ marginTop: 12 }}>
                  The render needs the plan as a JPEG or PNG. Upload it as an image in a new hunt.
                </p>
              )}
            </form>
          </div>
        )}
      </section>

      <section className="card" id="approve">
        <h2 className="section-title">Approve before searching</h2>
        {approved ? (
          <p>
            <span className="pill ok">Approved</span> {when(hunt.approved_at)}. Changing the BOQ cancels this approval.
          </p>
        ) : images.length === 0 || boqRows.length === 0 ? (
          <p className="locked">You need a BOQ and a 3D render first.</p>
        ) : (
          <form action={async (fd) => { "use server"; await approveHunt(fd); }}>
            <input type="hidden" name="id" value={hunt.id} />
            <fieldset>
              <legend>Choose the render you approve</legend>
              <div className="gallery">
                {images.map((name, i) => (
                  <label key={name}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`/hunts/${hunt.id}/image?n=${imageNum(name)}`} alt={`Render ${i + 1}`} />
                    <input type="radio" name="image" value={name} defaultChecked={i === images.length - 1} /> Render {i + 1}
                  </label>
                ))}
              </div>
            </fieldset>
            <button className="btn" type="submit">
              Approve BOQ and render
            </button>
          </form>
        )}
      </section>

      <section className="card" id="vendors">
        <h2 className="section-title">Find vendors</h2>
        {!approved ? (
          <p className="locked">The agents search only after you approve.</p>
        ) : (
          <form action={async (fd) => { "use server"; await startVendorSearch(fd); }}>
            <input type="hidden" name="id" value={hunt.id} />
            <fieldset>
              <legend>Items to source, up to 10</legend>
              <div className="fields">
                {boqRows.slice(0, 10).map((r: any) => (
                  <label className="check" key={r.id}>
                    <input type="checkbox" name="item" value={r.id} defaultChecked />
                    <span>{r.name}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <Submit pending="Starting…" className={hasListings ? "btn ghost" : "btn"}>
              {hasListings ? "Search again" : "Search vendors"}
            </Submit>
          </form>
        )}
        {steps.some((s: any) => s.agent === "Finder" || s.agent === "Checker") && (
          <details style={{ marginTop: 16 }}>
            <summary>What the agents did</summary>
            <Activity steps={steps} />
          </details>
        )}
      </section>

      <section className="card" id="quotes">
        <h2 className="section-title">Get quotes</h2>
        {quoteId && <AskQuote huntId={hunt.id} listingId={quoteId} vendors={vendors} />}
        {!hasListings ? (
          <p className="locked">Vendors will appear here after the search.</p>
        ) : (
          <>
            <p className="muted">
              Call or message a vendor where a phone number was found. Otherwise open their listing.
              Prices marked “web search” came from search results, so confirm them with the vendor.
            </p>
            {vendors.items.filter((g: any) => g.listings.length > 0).map((g: any) => (
              <div key={g.item} style={{ marginTop: 22 }}>
                <div className="section-head" style={{ marginBottom: 6 }}>
                  <h3>{g.item}</h3>
                  <span className="muted small">
                    {g.quantity} {g.unit} · {g.priced} with a price{g.blocked ? ` · ${g.blocked} couldn’t be checked` : ""}
                  </span>
                </div>
                <div className="table-wrap">
                  <table className="ledger">
                    <thead>
                      <tr>
                        <th>Vendor</th>
                        <th>Price</th>
                        <th>Delivery</th>
                        <th>Marked</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.listings.map((l: any) => (
                        <tr key={l.id}>
                          <td>
                            <a href={l.url} target="_blank" rel="noreferrer">
                              {l.seller || l.title || hostOf(l.url)}
                            </a>
                            <br />
                            <span className="muted small">
                              {[l.city, l.whatsapp && `+${phoneDigits(l.whatsapp)}`].filter(Boolean).join(" · ")}
                            </span>
                          </td>
                          <td>
                            {money(l.price, l.currency) ? (
                              <>
                                <span className="price">{money(l.price, l.currency)}</span>
                                {l.unit && <span className="muted small"> / {l.unit}</span>}
                                {!l.verified && (
                                  <>
                                    <br />
                                    <span className="muted small">web search</span>
                                  </>
                                )}
                              </>
                            ) : (
                              <span className="muted">{(l.verify_note || "").startsWith("Couldn't check") ? "Couldn’t check" : "Quote needed"}</span>
                            )}
                          </td>
                          <td>{l.delivery && !l.delivery.includes("<") ? l.delivery : "—"}</td>
                          <td>
                            {l.is_best && <span className="pill ok">Best</span>}{" "}
                            {l.is_cheapest && <span className="pill">Cheapest</span>}
                          </td>
                          <td>
                            <div className="actions">
                              {l.whatsapp ? (
                                <>
                                  <a className="btn small" href={`tel:+${phoneDigits(l.whatsapp)}`}>
                                    Call
                                  </a>
                                  <a className="btn ghost small" href={`/hunts/${hunt.id}?quote=${l.id}#quotes`}>
                                    Message
                                  </a>
                                </>
                              ) : (
                                <a className="btn ghost small" href={l.url} target="_blank" rel="noreferrer">
                                  Open listing
                                </a>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {g.best_reason && <p className="muted small" style={{ marginTop: 6 }}>{g.best_reason}</p>}
              </div>
            ))}
          </>
        )}
      </section>

      <Compare hunt={hunt} vendors={vendors} hasListings={hasListings} />
    </>
  );
}

function phoneDigits(phone: unknown) {
  return String(phone ?? "").replace(/\D/g, "");
}

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "Open listing";
  }
}

function imageNum(name: string) {
  return name.match(/_concept_(\d+)/)?.[1] ?? "1";
}

async function AskQuote({ huntId, listingId, vendors }: { huntId: number; listingId: string; vendors: any }) {
  const l = (vendors?.items ?? []).flatMap((g: any) => g.listings).find((x: any) => String(x.id) === String(listingId));
  const r = await previewText(`/api/listings/${listingId}/quote-request`, { seller_id: l?.seller_id ?? null });
  return (
    <div className="sheet" style={{ marginBottom: 20 }}>
      <h3 style={{ marginBottom: 8 }}>Ask {l?.seller || "this vendor"} for a quote</h3>
      {r?.preview && !l?.seller_opted_in && l?.whatsapp ? (
        <>
          <p className="muted">
            This vendor hasn’t agreed to automated messages, so this opens in your own WhatsApp with the message ready to send:
          </p>
          <p><em>{r.preview}</em></p>
          <p className="actions">
            <a
              className="btn"
              href={`https://wa.me/${phoneDigits(l.whatsapp)}?text=${encodeURIComponent(r.preview)}`}
              target="_blank"
              rel="noreferrer"
            >
              Open in WhatsApp
            </a>
            <a href={`/hunts/${huntId}#quotes`}>Cancel</a>
          </p>
          <VendorPicker huntId={huntId} listingId={listingId} />
        </>
      ) : r?.preview ? (
        <>
          <p className="muted">The exact WhatsApp message that will be sent:</p>
          <p><em>{r.preview}</em></p>
          <form action={async (fd) => { "use server"; await quoteRequest(fd); }} className="actions">
            <input type="hidden" name="hunt_id" value={huntId} />
            <input type="hidden" name="listing_id" value={listingId} />
            <input type="hidden" name="seller_id" value={l?.seller_id ?? ""} />
            <Submit pending="Sending…">Send on WhatsApp</Submit>
            <a href={`/hunts/${huntId}#quotes`}>Cancel</a>
          </form>
        </>
      ) : (
        <>
          <VendorPicker huntId={huntId} listingId={listingId} />
          {l?.whatsapp && (
            <p style={{ marginTop: 12 }}>
              Or <a href={`/hunts/${huntId}/invite/${listingId}`}>invite them from your own WhatsApp</a>.
            </p>
          )}
          <p style={{ marginTop: 12 }}>
            <a href={`/hunts/${huntId}#quotes`}>Cancel</a>
          </p>
        </>
      )}
    </div>
  );
}

function RoomForm({
  huntId,
  rows,
  blank,
  action,
}: {
  huntId: number;
  rows: any[];
  blank: number;
  action: string;
}) {
  const count = rows.length + blank;
  return (
    <form action={async (fd) => { "use server"; await confirmRooms(fd); }}>
      <input type="hidden" name="id" value={huntId} />
      <input type="hidden" name="count" value={count} />
      <div className="table-wrap">
        <table className="ledger">
          <thead>
            <tr>
              <th>Room</th>
              <th>Length, ft</th>
              <th>Width, ft</th>
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: count }, (_, i) => {
              const r = rows[i];
              const spec = jsonOf(r?.spec);
              return (
                <tr key={r?.id ?? `new-${i}`}>
                  <td>
                    <input className="input" name={`name-${i}`} defaultValue={r?.name ?? ""} maxLength={80} aria-label={`Room ${i + 1} name`} placeholder={r ? undefined : "Add a room"} />
                    <input type="hidden" name={`unit-${i}`} value={spec.unit || r?.unit || "ft"} />
                  </td>
                  <td>
                    <input className="input" name={`length-${i}`} type="number" step="any" min={0} defaultValue={spec.length ?? ""} aria-label={`Room ${i + 1} length`} />
                  </td>
                  <td>
                    <input className="input" name={`width-${i}`} type="number" step="any" min={0} defaultValue={spec.width ?? ""} aria-label={`Room ${i + 1} width`} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <button className="btn" type="submit" style={{ marginTop: 14 }}>
        {action}
      </button>
    </form>
  );
}

function Compare({ hunt, vendors, hasListings }: { hunt: any; vendors: any; hasListings: boolean }) {
  const items: any[] = vendors?.items ?? [];
  const priced = items.filter((g) => g.listings.some((l: any) => l.price != null));
  const line = (g: any, l: any) => (l?.price != null ? Number(l.price) * Number(g.quantity) : null);
  const running = priced.reduce((sum, g) => {
    const best = g.listings.find((l: any) => l.is_best) ?? g.listings.find((l: any) => l.is_cheapest);
    return sum + (line(g, best) ?? 0);
  }, 0);
  return (
    <section className="card" id="compare">
      <h2 className="section-title">Compare</h2>
      {!hasListings ? (
        <p className="locked">The best and cheapest vendor for each item will appear here.</p>
      ) : (
        <>
          <div className="figures" style={{ marginBottom: 20 }}>
            <div>
              <b>{priced.length} of {items.length}</b>
              <span className="muted small">items have a price</span>
            </div>
            <div>
              <b>{money(running) ?? "—"}</b>
              <span className="muted small">
                for priced items only{priced.length < items.length ? ", not the whole house" : ""}
              </span>
            </div>
          </div>
          <div className="table-wrap">
            <table className="ledger">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Best</th>
                  <th>Cheapest</th>
                  <th className="num">Best total</th>
                </tr>
              </thead>
              <tbody>
                {items.map((g: any) => {
                  const best = g.listings.find((l: any) => l.is_best);
                  const cheap = g.listings.find((l: any) => l.is_cheapest);
                  const same = best && cheap && best.id === cheap.id;
                  const show = (l: any) => (
                    <a href={l.url} target="_blank" rel="noreferrer">
                      {l.seller || "Vendor"}
                    </a>
                  );
                  return (
                    <tr key={g.item}>
                      <td>
                        <strong>{g.item}</strong>
                        <br />
                        <span className="muted small">{g.quantity} {g.unit}</span>
                      </td>
                      <td>
                        {best ? (
                          <>
                            {show(best)} · {money(best.price, best.currency)}
                            {best.unit && ` / ${best.unit}`}{" "}
                            {same && <span className="pill">Also cheapest</span>}
                          </>
                        ) : (
                          <span className="muted">Quote needed</span>
                        )}
                      </td>
                      <td>
                        {same ? (
                          <span className="muted">Same vendor</span>
                        ) : cheap ? (
                          <>
                            {show(cheap)} · {money(cheap.price, cheap.currency)}
                            {cheap.unit && ` / ${cheap.unit}`}
                          </>
                        ) : (
                          <span className="muted">Quote needed</span>
                        )}
                      </td>
                      <td className="num">{money(line(g, best ?? cheap)) ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

import { get, Expired, PageHead, Status, plainError, stepNote, when } from "@/lib/ui";
import DropForm from "./dropform";
import Refresh from "./[id]/refresh";

export const dynamic = "force-dynamic";

type Agent = { name: string; job: string; off?: boolean };

const SHOPPING: Agent[] = [
  { name: "Spotter", job: "Reads the item in your photo" },
  { name: "Finder", job: "Searches the web for similar listings" },
  { name: "Checker", job: "Checks price and stock on each page" },
  { name: "Matcher", job: "Compares each listing's photo with yours" },
  { name: "Ranker", job: "Ranks verified listings by total price" },
  { name: "Messenger", job: "Asks sellers on WhatsApp when you click" },
  { name: "Picker", job: "Picks the delivery option you prefer" },
  { name: "Buyer", job: "Sends the order you approve" },
  { name: "Tracker", job: "Chases the courier and tracking number" },
];
const CONSTRUCTION: Agent[] = [
  { name: "Plan Reader", job: "Reads rooms and sizes from your plan" },
  { name: "Quantity Surveyor", job: "Works out the BOQ from your rooms" },
  { name: "House Artist", job: "Renders the rooms in 3D from your plan" },
  { name: "Finder", job: "Finds vendors for each BOQ item" },
  { name: "Checker", job: "Checks each vendor's page for a price" },
  { name: "Ranker", job: "Marks the best and cheapest vendor" },
  { name: "Messenger", job: "Asks vendors for quotes on WhatsApp" },
  { name: "Quote Caller", job: "Calls vendors who agreed", off: true },
];

// Hunts: start a hunt from a photo or a floor plan, see the agents for that
// flow with real state from its latest hunt, then the hunt history.
export default async function HuntsPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; flow?: string }>;
}) {
  const { error, flow } = await searchParams;
  const h = await get("/api/hunts");
  if (h.expired) return <Expired />;
  const construction = flow === "construction";
  const flowName = construction ? "construction" : "shopping";
  const items: any[] = h.data.items ?? [];
  const latest = items.find((x) => x.flow === flowName);
  let panel: any = null;
  if (latest) {
    const d = await get(`/api/hunts/${latest.id}`);
    if (!d.expired && d.data) panel = d.data;
  }
  const byAgent: Record<string, any> = {};
  for (const s of panel?.steps ?? []) byAgent[s.agent] = s;
  const agents = construction ? CONSTRUCTION : SHOPPING;
  return (
    <main>
      <Refresh active={items.some((x) => x.status === "running")} />
      <PageHead
        title="What do you need?"
        note="Give the agents a photo or a floor plan. They search, check real prices, and contact vendors when you say so."
      />
      {error && <p className="notice">{error}</p>}
      <div className="split card">
        <section>
          <div className="tabs">
            <a href="/hunts?flow=shopping" aria-current={!construction ? "page" : undefined}>
              Find a product
            </a>
            <a href="/hunts?flow=construction" aria-current={construction ? "page" : undefined}>
              Plan a house
            </a>
          </div>
          <DropForm key={flowName} flow={flowName} />
        </section>
        <section>
          <div className="section-head">
            <h2>Your agents</h2>
            {latest && (
              <a className="small" href={`/hunts/${latest.id}`}>
                Latest hunt #{latest.id}
              </a>
            )}
          </div>
          <ul className="agents">
            {agents.map((a) => {
              const s = byAgent[a.name];
              return (
                <li key={a.name}>
                  <strong>{a.name}</strong>
                  <Status value={a.off ? "off" : s?.state ?? "ready"} />
                  <p>{stepNote(s, a.job)}</p>
                </li>
              );
            })}
          </ul>
        </section>
      </div>
      <section className="card">
        <h2 className="section-title">Past hunts</h2>
        {items.length === 0 ? (
          <p className="muted">Nothing yet. Your first hunt will appear here.</p>
        ) : (
          <div className="table-wrap">
            <table className="ledger">
              <thead>
                <tr>
                  <th>Hunt</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Result</th>
                  <th>Started</th>
                  <th className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {items.map((x) => (
                  <tr key={x.id}>
                    <td>
                      <a href={`/hunts/${x.id}`}>#{x.id}</a>
                    </td>
                    <td>{x.flow === "construction" ? "House" : "Product"}</td>
                    <td>
                      <Status value={x.status} />
                    </td>
                    <td className="muted">{x.top_reason || (x.status === "failed" ? plainError(x.error) : "")}</td>
                    <td className="muted">{when(x.created_at)}</td>
                    <td className="num">${Number(x.cost_usd).toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

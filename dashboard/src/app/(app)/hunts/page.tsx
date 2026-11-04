import { get, Expired } from "@/lib/ui";
import DropForm from "./dropform";

export const dynamic = "force-dynamic";

const AGENTS = [
  "Spotter", "Finder", "Checker", "Matcher", "Ranker", "Messenger",
  "Picker", "Buyer", "Tracker", "Plan Reader", "Quantity Surveyor",
  "House Artist", "Quote Caller",
];

// Hunts: start a hunt (product photo or house plan), the latest hunt's agent
// panel with real state from hunt_steps, then past hunts.
export default async function HuntsPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; flow?: string }>;
}) {
  const { error, flow } = await searchParams;
  const h = await get("/api/hunts");
  if (h.expired) return <Expired />;
  const construction = (flow ?? "shopping") === "construction";
  const items = h.data.items ?? [];
  // Agent panel: real steps of the latest hunt (list endpoint has no steps).
  let panel: any = null;
  if (items.length > 0) {
    const d = await get(`/api/hunts/${items[0].id}`);
    if (!d.expired && d.data) panel = d.data;
  }
  const byAgent: Record<string, any> = {};
  for (const s of panel?.steps ?? []) byAgent[s.agent] = s;
  return (
    <main>
      <div className="card">
        <h1>{construction ? "Plan a house" : "Find a product"}</h1>
        <p>
          <a href="/hunts?flow=shopping">Find a product</a> ·{" "}
          <a href="/hunts?flow=construction">Plan a house</a>
        </p>
        {error && <p className="pill bad">{error}</p>}
        <DropForm flow={construction ? "construction" : "shopping"} />
      </div>
      {panel && (
        <div className="card">
          <h2>
            Agents — latest hunt{" "}
            <a href={`/hunts/${panel.hunt.id}`}>#{panel.hunt.id}</a>{" "}
            <span className="pill">{panel.hunt.status}</span>
          </h2>
          <ul className="steps">
            {AGENTS.map((a) => {
              const s = byAgent[a];
              return (
                <li key={a}>
                  <strong>{a}</strong>{" "}
                  <span
                    className={`pill ${s?.state === "done" ? "ok" : s?.state === "failed" ? "bad" : ""}`}
                  >
                    {s?.state ?? "waiting"}
                  </span>{" "}
                  {s?.detail ?? ""} <span className="muted">{s?.at ?? ""}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      <div className="card">
        <h2>Past hunts</h2>
        {items.length === 0 && <p>No hunts yet.</p>}
        {items.map((x: any) => (
          <p key={x.id}>
            <a href={`/hunts/${x.id}`}>
              #{x.id} {x.flow === "construction" ? "House" : "Product"}
            </a>{" "}
            <span className="pill">{x.status}</span>{" "}
            <span className="muted">
              {x.searches_used} searches · ${Number(x.cost_usd).toFixed(4)}
            </span>
            {x.top_reason && (
              <>
                <br />
                <span className="muted">{x.top_reason}</span>
              </>
            )}
          </p>
        ))}
      </div>
    </main>
  );
}

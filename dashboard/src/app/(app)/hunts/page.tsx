import { get, Expired } from "@/lib/ui";
import { createHunt } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Hunts: start a hunt (product photo or house plan), then past hunts.
export default async function HuntsPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; flow?: string }>;
}) {
  const { error, flow } = await searchParams;
  const h = await get("/api/hunts");
  if (h.expired) return <Expired />;
  const construction = (flow ?? "shopping") === "construction";
  return (
    <main>
      <div className="card">
        <h1>{construction ? "Plan a house" : "Find a product"}</h1>
        <p>
          <a href="/hunts?flow=shopping">Find a product</a> ·{" "}
          <a href="/hunts?flow=construction">Plan a house</a>
        </p>
        {error && <p className="pill bad">{error}</p>}
        <form action={async (fd) => { "use server"; await createHunt(fd); }}>
          <input type="hidden" name="flow" value={construction ? "construction" : "shopping"} />
          <label>
            {construction ? "Floor plan (photo or PDF, max 8 MB)" : "Shirt photo (max 8 MB)"}
            <input className="input" type="file" name="file" accept="image/*,.pdf" required />
          </label>
          {!construction && (
            <>
              <label>
                Size <span className="norm">(optional)</span>
                <input className="input" name="size" maxLength={10} />
              </label>
              <label>
                Budget ₹ <span className="norm">(optional)</span>
                <input className="input" name="budget" type="number" min={0} />
              </label>
            </>
          )}
          {construction && (
            <>
              <label>
                City
                <input className="input" name="city" maxLength={80} required />
              </label>
              <label>
                Floors
                <input className="input" name="floors" type="number" min={1} defaultValue={1} />
              </label>
              <label>
                Floor height (ft)
                <input className="input" name="floor_height_ft" type="number" min={8} defaultValue={10} />
              </label>
              <label>
                Finish
                <select className="input" name="finish" defaultValue="standard">
                  <option value="basic">Basic</option>
                  <option value="standard">Standard</option>
                  <option value="premium">Premium</option>
                </select>
              </label>
              <label>
                Built-up sqft <span className="norm">(blank estimates from rooms × 1.2)</span>
                <input className="input" name="builtup_sqft" type="number" min={0} />
              </label>
            </>
          )}
          <button className="btn" type="submit">
            {construction ? "Check the plan" : "Start the hunt"}
          </button>
        </form>
      </div>
      <div className="card">
        <h2>Past hunts</h2>
        {h.data.items.length === 0 && <p>No hunts yet.</p>}
        {h.data.items.map((x: any) => (
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

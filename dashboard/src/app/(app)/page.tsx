import { get, Expired, Lang } from "@/lib/ui";

export const dynamic = "force-dynamic";

// Home: today's totals + calls table, "Load more" pages through.
export default async function Home({
  searchParams,
}: {
  searchParams: { before?: string };
}) {
  const s = await get("/api/stats");
  const c = await get(searchParams.before ? `/api/calls?before=${searchParams.before}` : "/api/calls");
  if (s.expired || c.expired) return <Expired />;
  return (
    <main>
      <div className="card">
        <h1>Today</h1>
        <p>
          {s.data.calls} calls · {s.data.bookings} bookings · {s.data.open_tasks} open tasks (
          {s.data.urgent_tasks} urgent) · ${Number(s.data.cost_usd).toFixed(4)}
        </p>
      </div>
      <div className="card">
        <h1>Calls</h1>
        {c.data.items.length === 0 && <p>No calls yet. Add your business info to start.</p>}
        {c.data.items.map((call: any) => (
          <p key={call.id}>
            <a href={`/calls/${call.id}`}>{call.contact.name || "Unknown"}</a> <Lang code={call.language} />{" "}
            {call.outcome} · {call.duration_s}s · ${Number(call.cost_usd).toFixed(4)}
          </p>
        ))}
        {c.data.next_before && <a href={`/?before=${c.data.next_before}`}>Load more</a>}
      </div>
    </main>
  );
}

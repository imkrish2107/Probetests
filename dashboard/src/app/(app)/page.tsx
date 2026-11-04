import { get, Expired, Lang, PageHead, when } from "@/lib/ui";

export const dynamic = "force-dynamic";

// Voice agent calls: today's figures and the calls table, "Load more" pages through.
export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ before?: string }>;
}) {
  const { before } = await searchParams;
  const s = await get("/api/stats");
  const c = await get(before ? `/api/calls?before=${before}` : "/api/calls");
  if (s.expired || c.expired) return <Expired />;
  const items: any[] = c.data.items ?? [];
  return (
    <main>
      <PageHead title="Calls" note="Every call the voice agent took, with its transcript and outcome." />
      <div className="figures card">
        <div><b>{s.data.calls}</b><span className="muted small">calls today</span></div>
        <div><b>{s.data.open_tasks}</b><span className="muted small">open tasks, {s.data.urgent_tasks} urgent</span></div>
        <div><b>${Number(s.data.cost_usd).toFixed(3)}</b><span className="muted small">model cost today</span></div>
      </div>
      {items.length === 0 ? (
        <p className="muted">No calls yet. They appear here as soon as someone calls your WhatsApp number.</p>
      ) : (
        <div className="table-wrap">
          <table className="ledger">
            <thead>
              <tr>
                <th>Caller</th>
                <th>Language</th>
                <th>Outcome</th>
                <th>Started</th>
                <th className="num">Length</th>
                <th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {items.map((call) => (
                <tr key={call.id}>
                  <td><a href={`/calls/${call.id}`}>{call.contact?.name || "Unknown"}</a></td>
                  <td><Lang code={call.language} /></td>
                  <td>{call.outcome}</td>
                  <td className="muted">{when(call.started_at)}</td>
                  <td className="num">{call.duration_s}s</td>
                  <td className="num">${Number(call.cost_usd).toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {c.data.next_before && <p style={{ marginTop: 16 }}><a href={`/?before=${c.data.next_before}`}>Load more</a></p>}
    </main>
  );
}

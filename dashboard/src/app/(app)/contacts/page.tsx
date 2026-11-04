import { get, Expired, Lang } from "@/lib/ui";

export const dynamic = "force-dynamic";

// Search + customer list.
export default async function ContactsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; before?: string }>;
}) {
  const search = await searchParams;
  const params = new URLSearchParams();
  if (search.q) params.set("q", search.q);
  if (search.before) params.set("before", search.before);
  const { data, expired } = await get(`/api/contacts?${params}`);
  if (expired || !data) return <Expired />;
  return (
    <main>
      <div className="card">
        <h1>Contacts</h1>
        <form method="GET">
          <input className="input" name="q" placeholder="Search name or number" defaultValue={search.q ?? ""} />
          <button type="submit">Search</button>
        </form>
        {data.items.length === 0 && <p>No contacts yet.</p>}
        {data.items.map((c: any) => (
          <p key={c.id}>
            <a href={`/contacts/${c.id}`}>{c.name || "Unknown"}</a> <Lang code={c.language} />{" "}
            {c.stage} · {c.phone_masked} · {c.calls_count} calls
          </p>
        ))}
        {data.next_before && (
          <a href={`/contacts?q=${search.q ?? ""}&before=${data.next_before}`}>Load more</a>
        )}
      </div>
    </main>
  );
}

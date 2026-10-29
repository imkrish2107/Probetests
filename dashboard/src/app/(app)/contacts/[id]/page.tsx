import { get, Expired, Lang } from "@/lib/ui";
import { updateContact, callButton, aiCallback } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Contact detail: editable stage/tags/notes, full history, call buttons.
export default async function ContactPage({ params }: { params: { id: string } }) {
  const { data: c, expired } = await get(`/api/contacts/${params.id}`);
  if (expired || !c) return <Expired />;
  return (
    <main>
      <div className="card">
        <h1>
          {c.name || "Unknown"} <Lang code={c.language} /> {c.stage}
        </h1>
        <p>
          {c.phone || "no number"} · {c.calls_count} calls · permission:{" "}
          {c.call_permission ? "yes" : "no"}
        </p>
        <form action={updateContact}>
          <input type="hidden" name="id" value={c.id} />
          <label>
            Name
            <input className="input" name="name" defaultValue={c.name ?? ""} />
          </label>
          <label>
            Stage
            <select className="input" name="stage" defaultValue={c.stage}>
              <option value="new">new</option>
              <option value="lead">lead</option>
              <option value="booked">booked</option>
              <option value="customer">customer</option>
            </select>
          </label>
          <label>
            Tags (comma separated)
            <input className="input" name="tags" defaultValue={(c.tags ?? []).join(", ")} />
          </label>
          <label>
            Notes
            <input className="input" name="notes" defaultValue={c.notes ?? ""} />
          </label>
          <button type="submit">Save</button>
        </form>
        <form action={callButton}>
          <input type="hidden" name="contact_id" value={c.id} />
          <button className="btn" type="submit">
            Send call button
          </button>
        </form>
        {c.call_permission ? (
          <form action={aiCallback}>
            <input type="hidden" name="contact_id" value={c.id} />
            <button type="submit">AI call back</button>
          </form>
        ) : (
          <p>AI call back: Customer hasn&apos;t allowed calls yet</p>
        )}
      </div>
      <div className="card">
        <h2>Calls</h2>
        {c.calls.map((call: any) => (
          <p key={call.id}>
            <a href={`/calls/${call.id}`}>#{call.id}</a> {call.started_at} · {call.outcome}
          </p>
        ))}
        {c.calls.length === 0 && <p>No calls.</p>}
      </div>
      <div className="card">
        <h2>Bookings & tasks</h2>
        {c.bookings.map((b: any) => (
          <p key={b.id}>
            Booking: {b.slot} · {b.party_size} · {b.status}
          </p>
        ))}
        {c.tasks.map((t: any) => (
          <p key={t.id}>
            Task: {t.type} — {t.details} ({t.status})
          </p>
        ))}
      </div>
    </main>
  );
}

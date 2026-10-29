import { get, Expired } from "@/lib/ui";
import { taskDone, callButton } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Open tasks, urgent first. Mark done asks for a note (sent to the customer).
export default async function TasksPage({
  searchParams,
}: {
  searchParams: { status?: string };
}) {
  const status = searchParams.status === "done" ? "done" : "open";
  const { data, expired } = await get(`/api/tasks?status=${status}`);
  if (expired || !data) return <Expired />;
  return (
    <main>
      <div className="card">
        <h1>Tasks · {status}</h1>
        <p>
          <a href="/tasks">Open</a> · <a href="/tasks?status=done">Done</a>
        </p>
        {data.items.length === 0 && <p>No {status} tasks.</p>}
        {data.items.map((t: any) => (
          <div key={t.id}>
            <p>
              [{t.urgency}] {t.type} — {t.details} · {t.contact?.name} ·{" "}
              <a href={`/contacts/${t.contact?.id}`}>contact</a>
              {t.call_id ? (
                <>
                  {" "}· <a href={`/calls/${t.call_id}`}>call</a>
                </>
              ) : null}
            </p>
            {status === "open" && (
              <>
                <form action={taskDone}>
                  <input type="hidden" name="id" value={t.id} />
                  <input className="input" name="note" placeholder="Quote / update for customer" required />
                  <button type="submit">Mark done</button>
                </form>
                <form action={callButton}>
                  <input type="hidden" name="contact_id" value={t.contact?.id} />
                  <button type="submit">Send call button</button>
                </form>
              </>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}

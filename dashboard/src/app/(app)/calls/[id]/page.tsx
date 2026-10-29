import { get, Expired, Lang } from "@/lib/ui";
import { callButton } from "@/lib/actions";

export const dynamic = "force-dynamic";

// One call: transcript, summary, bookings/tasks/messages, cost + send call button.
export default async function CallPage({ params }: { params: { id: string } }) {
  const { data: call, expired } = await get(`/api/calls/${params.id}`);
  if (expired || !call) return <Expired />;
  return (
    <main>
      <div className="card">
        <h1>
          Call #{call.id} <Lang code={call.language} /> {call.outcome}
        </h1>
        <p>
          {call.started_at} · {call.duration_s}s · {call.direction}
          {call.source ? ` · via ${call.source}` : ""}
        </p>
        {call.summary && <p>{call.summary}</p>}
        <p>
          Tokens {call.tokens_in}/{call.tokens_out} · audio {call.audio_seconds}s · cost $
          {Number(call.cost_usd).toFixed(4)}
        </p>
        {call.contact_id && (
          <form action={callButton}>
            <input type="hidden" name="contact_id" value={call.contact_id} />
            <button className="btn" type="submit">
              Send call button
            </button>
          </form>
        )}
      </div>
      <div className="card">
        <h2>Transcript</h2>
        {call.transcript.map((t: any, i: number) => (
          <p key={i} className={t.role === "agent" ? "bubble-right" : "bubble-left"}>
            <Lang code={t.language} /> {t.text}
          </p>
        ))}
        {call.transcript.length === 0 && <p>No transcript.</p>}
      </div>
      {(call.bookings?.length > 0 || call.tasks?.length > 0) && (
        <div className="card">
          <h2>From this call</h2>
          {call.bookings.map((b: any) => (
            <p key={b.id}>
              Booking: {b.name}, {b.party_size} people, {b.slot} ({b.status})
            </p>
          ))}
          {call.tasks.map((t: any) => (
            <p key={t.id}>
              Task: {t.type} — {t.details} ({t.urgency}, {t.status})
            </p>
          ))}
        </div>
      )}
      {call.messages?.length > 0 && (
        <div className="card">
          <h2>Messages</h2>
          {call.messages.map((m: any) => (
            <p key={m.id}>
              {m.kind} · {m.status}
              {m.error ? ` · ${m.error}` : ""}
            </p>
          ))}
        </div>
      )}
    </main>
  );
}

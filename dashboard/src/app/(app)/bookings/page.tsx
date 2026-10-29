import { get, Expired } from "@/lib/ui";
import { bookingMove, bookingCancel } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Day view with date picker; Move / Cancel notify the customer.
export default async function BookingsPage({
  searchParams,
}: {
  searchParams: { date?: string };
}) {
  const date = searchParams.date ?? new Date().toISOString().slice(0, 10);
  const { data, expired } = await get(`/api/bookings?date=${date}`);
  if (expired || !data) return <Expired />;
  return (
    <main>
      <div className="card">
        <h1>Bookings · {date}</h1>
        <form method="GET">
          <input className="input" type="date" name="date" defaultValue={date} />
          <button type="submit">Go</button>
        </form>
        {data.items.length === 0 && <p>No bookings this day.</p>}
        {data.items.map((b: any) => (
          <div key={b.id}>
            <p>
              {b.slot} · {b.name} · {b.party_size} people · {b.status}
              {b.note ? ` · ${b.note}` : ""}
              {b.reminder_sent_at ? " · reminded" : ""}
            </p>
            {b.status !== "cancelled" && (
              <>
                <form action={bookingMove}>
                  <input type="hidden" name="id" value={b.id} />
                  <input type="hidden" name="date" value={date} />
                  <input className="input" type="datetime-local" name="slot" required />
                  <button type="submit">Move</button>
                </form>
                <form action={bookingCancel}>
                  <input type="hidden" name="id" value={b.id} />
                  <input type="hidden" name="date" value={date} />
                  <button type="submit">Cancel</button>
                </form>
              </>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}

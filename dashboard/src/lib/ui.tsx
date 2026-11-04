import { api, sessionToken, ApiError } from "./api";

// GET that turns an expired session into {expired} instead of a 500.
export async function get(path: string) {
  try {
    return { data: await api(path, undefined, await sessionToken()) };
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return { expired: true as const };
    throw e;
  }
}

export function Expired() {
  return (
    <main>
      <div className="empty">
        <h2>Your session has ended</h2>
        <p>Log in again to carry on.</p>
        <a className="btn" href="/login">
          Log in
        </a>
      </div>
    </main>
  );
}

export function PageHead({
  title,
  note,
  crumb,
  children,
}: {
  title: React.ReactNode;
  note?: React.ReactNode;
  crumb?: { href: string; text: string };
  children?: React.ReactNode;
}) {
  return (
    <header className="head">
      <div>
        {crumb && (
          <a className="crumb" href={crumb.href}>
            {crumb.text}
          </a>
        )}
        <h1>{title}</h1>
        {note && <p className="note">{note}</p>}
      </div>
      {children && <div className="actions">{children}</div>}
    </header>
  );
}

export function Empty({
  title,
  children,
  href,
  cta,
}: {
  title: string;
  children: React.ReactNode;
  href?: string;
  cta?: string;
}) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      <p>{children}</p>
      {href && (
        <a className="btn" href={href}>
          {cta}
        </a>
      )}
    </div>
  );
}

const WORDS: Record<string, string> = {
  running: "Working",
  queued: "Queued",
  done: "Done",
  failed: "Failed",
  ready: "Ready",
  off: "Off",
  awaiting_rooms: "Check the rooms",
  rooms_confirmed: "Rooms confirmed",
  boq_ready: "BOQ ready",
  approved: "Approved",
  draft: "Draft",
  order_sent: "Order sent",
  seller_confirmed: "Seller confirmed",
  seller_declined: "Seller declined",
  shipped: "Shipped",
  delivered: "Delivered",
  cancelled: "Cancelled",
  needs_attention: "Needs attention",
};

export function statusWord(s: string) {
  return WORDS[s] ?? (s || "").replace(/_/g, " ");
}

export function Status({ value }: { value: string }) {
  const good = ["done", "approved", "delivered", "seller_confirmed"].includes(value);
  const bad = ["failed", "needs_attention", "seller_declined", "cancelled"].includes(value);
  const live = value === "running";
  return (
    <span className={`pill ${good ? "ok" : bad ? "bad" : live ? "live" : ""}`}>
      {statusWord(value)}
    </span>
  );
}

// Agent errors can be raw internal text. Only known messages reach the screen.
export function plainError(text?: string | null) {
  const t = (text || "").toLowerCase();
  if (t.includes("no garment")) return "No clothing item could be seen in that photo. Try a clearer one.";
  if (t.includes("no product pages")) return "No product pages were found for this search.";
  if (t.includes("unreadable")) return "The plan couldn’t be read. Enter the rooms yourself.";
  if (t.includes("one hunt at a time")) return "Another hunt is still running.";
  return "This step couldn’t finish. Please try again.";
}

export function stepNote(s: { state?: string; detail?: string } | undefined, fallback = "") {
  if (!s) return fallback;
  return s.state === "failed" ? plainError(s.detail) : s.detail || fallback;
}

// Listing and order prices. Null means the vendor has not given one.
export function money(price: unknown, currency?: string | null) {
  if (price === null || price === undefined || price === "") return null;
  const n = Number(price);
  if (!Number.isFinite(n)) return null;
  const sym = !currency || currency === "INR" ? "₹" : `${currency} `;
  return `${sym}${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

// Backend times are UTC. Shown in India time for this deployment.
export function when(at?: string | null) {
  if (!at) return "";
  const iso = at.includes("T") ? at : `${at.replace(" ", "T")}Z`;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return at;
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Short language pill (EN, HI, TA…) so multi-language is obvious.
export function Lang({ code }: { code: string }) {
  const short: Record<string, string> = {
    en: "EN", hi: "HI", ta: "TA", te: "TE", kn: "KN", bn: "BN", mr: "MR",
    english: "EN", hindi: "HI", tamil: "TA",
  };
  const s = short[(code || "").toLowerCase()] ?? (code || "?").slice(0, 2).toUpperCase();
  return <span className="pill">{s}</span>;
}

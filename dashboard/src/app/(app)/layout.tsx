import { api, sessionToken } from "@/lib/api";
import { logout } from "@/lib/actions";
import Nav from "./nav";

export const dynamic = "force-dynamic";

// Side rail on every logged-in page (a top strip on phones).
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  let name = "";
  try {
    const me = await api("/api/auth/me", undefined, await sessionToken());
    name = me.user.name;
  } catch {
    // middleware keeps logged-out users away; expired sessions 401 on page fetch
  }
  return (
    <div className="shell">
      <aside className="side">
        <a className="brand" href="/hunts">
          Agent dashboard
        </a>
        <Nav />
        <div className="side-foot">
          <strong>{name}</strong>
          <form action={async () => { "use server"; await logout(); }}>
            <button type="submit">Log out</button>
          </form>
        </div>
      </aside>
      {children}
    </div>
  );
}

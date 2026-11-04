import { api, sessionToken } from "@/lib/api";
import { logout } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Top bar on every logged-in page.
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  let name = "";
  try {
    const me = await api("/api/auth/me", undefined, await sessionToken());
    name = me.user.name;
  } catch {
    // middleware keeps logged-out users away; expired sessions 401 on page fetch
  }
  return (
    <>
      <nav className="topbar">
        <a href="/hunts">Agent dashboard</a>
        <a href="/hunts">Hunts</a>
        <a href="/orders">Orders</a>
        <a href="/sellers">Sellers</a>
        <a href="/setup">Setup</a>
        <a href="/">Calls</a>
        <a href="/contacts">Contacts</a>
        <a href="/tasks">Tasks</a>
        <span className="spacer" />
        <span>{name}</span>
        <form action={async () => { await logout(); }}>
          <button type="submit">Log out</button>
        </form>
      </nav>
      {children}
    </>
  );
}

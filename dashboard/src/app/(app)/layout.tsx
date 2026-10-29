import { api, sessionToken } from "@/lib/api";
import { logout } from "@/lib/actions";

export const dynamic = "force-dynamic";

// Top bar on every logged-in page.
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  let name = "";
  try {
    const me = await api("/api/auth/me", undefined, sessionToken());
    name = me.user.name;
  } catch {
    // middleware keeps logged-out users away; expired sessions 401 on page fetch
  }
  return (
    <>
      <nav className="topbar">
        <a href="/">Calls</a>
        <a href="/bookings">Bookings</a>
        <a href="/tasks">Tasks</a>
        <a href="/contacts">Contacts</a>
        <a href="/setup">Setup</a>
        <span className="spacer" />
        <span>{name}</span>
        <form action={logout}>
          <button type="submit">Log out</button>
        </form>
      </nav>
      {children}
    </>
  );
}

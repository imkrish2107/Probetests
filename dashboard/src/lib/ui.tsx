import { api, sessionToken, ApiError } from "./api";

// GET that turns an expired session into {expired} instead of a 500.
export async function get(path: string) {
  try {
    return { data: await api(path, undefined, sessionToken()) };
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return { expired: true as const };
    throw e;
  }
}

export function Expired() {
  return (
    <main>
      <div className="card">
        <p>
          Session expired. <a href="/login">Log in again</a>
        </p>
      </div>
    </main>
  );
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

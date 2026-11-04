import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Behind nginx, req.url resolves to the app's internal address (localhost:3000),
// so redirects are built from the Host header nginx passes through.
function redirectTo(req: NextRequest, path: string) {
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host") ?? req.nextUrl.host;
  const proto = req.headers.get("x-forwarded-proto") ?? req.nextUrl.protocol.replace(":", "");
  return NextResponse.redirect(new URL(path, `${proto}://${host}`));
}

// No session cookie -> /login. Logged in + visiting /login|/signup -> /hunts.
export function middleware(req: NextRequest) {
  const session = req.cookies.get("session")?.value;
  const path = req.nextUrl.pathname;
  const isAuth = path.startsWith("/login") || path.startsWith("/signup");
  const isPublicCall = path.startsWith("/c/");
  if (!session && !isAuth && !isPublicCall) {
    return redirectTo(req, "/login");
  }
  if (session && isAuth) {
    return redirectTo(req, "/hunts");
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

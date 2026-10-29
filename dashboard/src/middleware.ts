import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// No session cookie -> /login. Logged in + visiting /login|/signup -> /.
export function middleware(req: NextRequest) {
  const session = req.cookies.get("session")?.value;
  const path = req.nextUrl.pathname;
  const isAuth = path.startsWith("/login") || path.startsWith("/signup");
  const isPublicCall = path.startsWith("/c/");
  if (!session && !isAuth && !isPublicCall) {
    return NextResponse.redirect(new URL("/login", req.url));
  }
  if (session && isAuth) {
    return NextResponse.redirect(new URL("/", req.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

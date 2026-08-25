import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isPublic = PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"));

  // Never intercept API proxy traffic: /backend/* is the authenticated
  // server-side proxy to FastAPI (login itself posts there), and /api/*
  // is reserved. Redirecting these would break auth requests.
  if (pathname.startsWith("/api/") || pathname.startsWith("/backend/")) {
    return NextResponse.next();
  }

  // Must match SESSION_COOKIE_NAME in the FastAPI backend.
  const token = request.cookies.get("modeem_session");

  if (!token && !isPublic) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  if (token && isPublic) {
    const dashboardUrl = new URL("/", request.url);
    return NextResponse.redirect(dashboardUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

/**
 * Server-side proxy: /backend/** → http://localhost:8000/**
 *
 * This file is intentionally thin — all logic lives in:
 *   lib/tenant-resolver.ts  — resolveTenantFromRequest (plug-in point for the login task)
 *   lib/proxy-handler.ts    — guard + upstream forwarding, returns ProxyResult
 *
 * To add session-based auth when the login task lands:
 *   1. Implement getSessionTenant() in lib/tenant-resolver.ts
 *   2. Plug it into the `return null` branch of resolveTenantFromRequest()
 *   No changes needed here.
 */

import { type NextRequest, NextResponse } from "next/server";
import { proxyRequest } from "@/lib/proxy-handler";

type Ctx = { params: Promise<{ path: string[] }> };

async function handle(req: NextRequest, { params }: Ctx): Promise<NextResponse> {
  const { path } = await params;
  const result = await proxyRequest(req, path, req.nextUrl.search);
  const headers = new Headers({ "Content-Type": result.contentType });
  if (result.setCookie) headers.set("Set-Cookie", result.setCookie);
  return new NextResponse(result.body, { status: result.status, headers });
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;

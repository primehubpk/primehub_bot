import { NextRequest, NextResponse } from "next/server";

function allowedOrigins() {
  return (process.env.ALLOWED_WEBSITE_ORIGINS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function isAllowed(origin: string | null) {
  return Boolean(origin && allowedOrigins().includes(origin));
}

export function middleware(request: NextRequest) {
  const origin = request.headers.get("origin");
  const path = request.nextUrl.pathname;
  const allowed = isAllowed(origin);

  if (request.method === "OPTIONS" && path.startsWith("/api/")) {
    if (!allowed) return new NextResponse(null, { status: 204 });
    return new NextResponse(null, {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": origin!,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        Vary: "Origin",
      },
    });
  }

  const response = NextResponse.next();

  if (path.startsWith("/api/") && allowed) {
    response.headers.set("Access-Control-Allow-Origin", origin!);
    response.headers.set("Access-Control-Allow-Credentials", "true");
    response.headers.set("Vary", "Origin");
  }

  if (path.startsWith("/embed")) {
    const frameAncestors = ["'self'", ...allowedOrigins()].join(" ");
    response.headers.set("Content-Security-Policy", `frame-ancestors ${frameAncestors}`);
    response.headers.set("Cache-Control", "no-store");
  }

  return response;
}

export const config = {
  matcher: ["/api/:path*", "/embed/:path*"],
};

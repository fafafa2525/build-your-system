/**
 * Shared token check for /api/public/bot/* endpoints.
 * The VPS sends: Authorization: Bearer <BOT_API_TOKEN>
 * Runs on the server only.
 */
import { timingSafeEqual } from "node:crypto";

export function checkBotToken(request: Request): Response | null {
  const expected = process.env.BOT_API_TOKEN;
  if (!expected) {
    return new Response(JSON.stringify({ error: "BOT_API_TOKEN not configured" }), {
      status: 500,
      headers: { "content-type": "application/json" },
    });
  }
  const header = request.headers.get("authorization") ?? "";
  const provided = header.startsWith("Bearer ") ? header.slice(7) : "";
  const a = Buffer.from(provided);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    return new Response(JSON.stringify({ error: "unauthorized" }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }
  return null;
}

export function jsonError(msg: string, status = 400): Response {
  return new Response(JSON.stringify({ error: msg }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

import { createFileRoute } from "@tanstack/react-router";
import { checkBotToken, json, jsonError } from "@/lib/bot-auth";

export const Route = createFileRoute("/api/public/bot/logs")({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const body = (await request.json()) as {
          search_id?: string;
          level?: string;
          message: string;
          meta?: unknown;
        };
        if (!body.message) return jsonError("message required");
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const { error } = await supabaseAdmin.from("job_logs").insert({
          search_id: body.search_id ?? null,
          level: body.level ?? "info",
          message: body.message,
          meta: body.meta ?? null,
        });
        if (error) return jsonError(error.message, 500);
        return json({ ok: true });
      },
    },
  },
});

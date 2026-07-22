import { createFileRoute } from "@tanstack/react-router";
import { checkBotToken, json, jsonError } from "@/lib/bot-auth";

export const Route = createFileRoute("/api/public/bot/heartbeat")({
  server: {
    handlers: {
      // Bot pings every ~30s: { service: 'vps' | 'telegram_bot' | 'apify', status, details? }
      POST: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const body = (await request.json()) as { service: string; status?: string; details?: unknown };
        if (!body.service) return jsonError("service required");
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const { error } = await supabaseAdmin.from("health_status").upsert(
          {
            service: body.service,
            status: body.status ?? "online",
            last_heartbeat: new Date().toISOString(),
            details: body.details ?? null,
          },
          { onConflict: "service" }
        );
        if (error) return jsonError(error.message, 500);
        return json({ ok: true });
      },
    },
  },
});

import { createFileRoute } from "@tanstack/react-router";
import { checkBotToken, json, jsonError } from "@/lib/bot-auth";

// Read-only settings endpoint the VPS bot uses to know its Telegram allow-list.
export const Route = createFileRoute("/api/public/bot/settings")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const { data, error } = await supabaseAdmin
          .from("bot_settings")
          .select("allowed_telegram_ids, default_country, default_max_pages, auto_send_results")
          .eq("id", 1)
          .single();
        if (error) return jsonError(error.message, 500);
        return json(data);
      },
    },
  },
});

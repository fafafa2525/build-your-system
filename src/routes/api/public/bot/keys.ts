import { createFileRoute } from "@tanstack/react-router";
import { checkBotToken, json, jsonError } from "@/lib/bot-auth";

export const Route = createFileRoute("/api/public/bot/keys")({
  server: {
    handlers: {
      // GET active keys (worker fetches on each search)
      GET: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const { data, error } = await supabaseAdmin
          .from("apify_keys")
          .select("id, label, api_key, status, usage_count, last_used_at")
          .eq("status", "active")
          .order("last_used_at", { ascending: true, nullsFirst: true });
        if (error) return jsonError(error.message, 500);
        return json({ keys: data });
      },

      // POST add a new key (from Telegram /addkey)
      POST: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const body = (await request.json()) as { api_key: string; label?: string };
        if (!body.api_key?.startsWith("apify_api_")) return jsonError("invalid apify key format");
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const { data, error } = await supabaseAdmin
          .from("apify_keys")
          .insert({
            api_key: body.api_key.trim(),
            label: body.label || `Telegram - ${new Date().toLocaleDateString()}`,
            status: "active",
            added_via: "telegram",
          })
          .select()
          .single();
        if (error) {
          if (error.code === "23505") return jsonError("هذا المفتاح موجود مسبقاً", 409);
          return jsonError(error.message, 500);
        }
        return json({ key: data });
      },

      // PATCH update usage / mark exhausted
      PATCH: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const body = (await request.json()) as {
          id: string;
          status?: string;
          increment_usage?: boolean;
          last_error?: string;
        };
        if (!body.id) return jsonError("id required");
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const now = new Date().toISOString();
        const patch: Record<string, unknown> = { last_used_at: now };
        if (body.status) patch.status = body.status;
        if (body.last_error) {
          patch.last_error = body.last_error;
          patch.last_error_at = now;
        } else if (body.status === "active" || body.increment_usage) {
          patch.last_success_at = now;
        }
        // Fetch current for increments
        const { data: cur } = await supabaseAdmin
          .from("apify_keys")
          .select("usage_count, daily_usage, monthly_usage, daily_reset_at, monthly_reset_at")
          .eq("id", body.id)
          .single();
        if (cur && body.increment_usage) {
          const today = new Date().toISOString().slice(0, 10);
          const monthStart = new Date().toISOString().slice(0, 7) + "-01";
          const dailyReset = cur.daily_reset_at !== today;
          const monthlyReset = cur.monthly_reset_at !== monthStart;
          patch.usage_count = (cur.usage_count ?? 0) + 1;
          patch.daily_usage = dailyReset ? 1 : (cur.daily_usage ?? 0) + 1;
          patch.monthly_usage = monthlyReset ? 1 : (cur.monthly_usage ?? 0) + 1;
          if (dailyReset) patch.daily_reset_at = today;
          if (monthlyReset) patch.monthly_reset_at = monthStart;
        }
        const { data, error } = await supabaseAdmin.from("apify_keys").update(patch as any).eq("id", body.id).select().single();
        if (error) return jsonError(error.message, 500);
        return json({ key: data });
      },
    },
  },
});

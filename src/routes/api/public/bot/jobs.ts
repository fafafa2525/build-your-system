import { createFileRoute } from "@tanstack/react-router";
import { checkBotToken, json, jsonError } from "@/lib/bot-auth";

export const Route = createFileRoute("/api/public/bot/jobs")({
  server: {
    handlers: {
      // Create a new search job (called by Telegram bot /search)
      POST: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const body = (await request.json()) as {
          keyword: string;
          country: string;
          max_pages?: number;
          telegram_chat_id?: number;
          telegram_user_id?: number;
        };
        if (!body.keyword || !body.country) return jsonError("keyword and country required");
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const { data, error } = await supabaseAdmin
          .from("searches")
          .insert({
            keyword: body.keyword,
            country: body.country,
            max_pages: body.max_pages ?? 100,
            telegram_chat_id: body.telegram_chat_id ?? null,
            telegram_user_id: body.telegram_user_id ?? null,
            source: "telegram",
            status: "pending",
          })
          .select()
          .single();
        if (error) return jsonError(error.message, 500);
        return json({ job: data });
      },

      // Worker polls: GET ?next=1 claims next pending job
      GET: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const url = new URL(request.url);
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        if (url.searchParams.get("next")) {
          // Atomically claim: pending -> running
          const { data: pending } = await supabaseAdmin
            .from("searches")
            .select("*")
            .eq("status", "pending")
            .order("created_at", { ascending: true })
            .limit(1)
            .maybeSingle();
          if (!pending) return json({ job: null });
          const { data: claimed, error } = await supabaseAdmin
            .from("searches")
            .update({ status: "running", started_at: new Date().toISOString(), progress: 0 })
            .eq("id", pending.id)
            .eq("status", "pending")
            .select()
            .single();
          if (error || !claimed) return json({ job: null });
          return json({ job: claimed });
        }
        return jsonError("unsupported query", 400);
      },

      // Worker updates job status/progress
      PATCH: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const body = (await request.json()) as {
          id: string;
          status?: string;
          progress?: number;
          progress_message?: string;
          pages_found?: number;
          numbers_found?: number;
          numbers_new?: number;
          error_message?: string;
          apify_run_id?: string;
          finished?: boolean;
        };
        if (!body.id) return jsonError("id required");
        const patch: Record<string, unknown> = {};
        for (const k of ["status", "progress", "progress_message", "pages_found", "numbers_found", "numbers_new", "error_message", "apify_run_id"]) {
          if (k in body) patch[k] = (body as any)[k];
        }
        if (body.finished) {
          patch.finished_at = new Date().toISOString();
        }
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        // Compute duration if finishing
        if (body.finished) {
          const { data: cur } = await supabaseAdmin.from("searches").select("started_at").eq("id", body.id).single();
          if (cur?.started_at) {
            patch.duration_seconds = Math.floor((Date.now() - new Date(cur.started_at).getTime()) / 1000);
          }
        }
        const { data, error } = await supabaseAdmin.from("searches").update(patch).eq("id", body.id).select().single();
        if (error) return jsonError(error.message, 500);
        return json({ job: data });
      },
    },
  },
});

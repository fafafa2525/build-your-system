import { createFileRoute } from "@tanstack/react-router";
import { checkBotToken, json, jsonError } from "@/lib/bot-auth";

/**
 * Apify Platform layer API (Layer 1).
 * One endpoint, multiple resources via ?resource=
 *   actors | favorites | runs | templates
 */

const RESOURCES = ["actors", "favorites", "runs", "templates"] as const;
type Resource = (typeof RESOURCES)[number];

const TABLE: Record<Resource, string> = {
  actors: "apify_actors",
  favorites: "apify_favorites",
  runs: "apify_runs",
  templates: "apify_templates",
};

function resourceOf(url: URL): Resource | null {
  const r = url.searchParams.get("resource") as Resource | null;
  return r && (RESOURCES as readonly string[]).includes(r) ? r : null;
}

export const Route = createFileRoute("/api/public/bot/apify")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const url = new URL(request.url);
        const resource = resourceOf(url);
        if (!resource) return jsonError("unknown resource");
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const limit = Math.min(Number(url.searchParams.get("limit") ?? 200), 1000);

        if (resource === "actors") {
          let q = supabaseAdmin.from("apify_actors").select("*").limit(limit);
          const category = url.searchParams.get("category");
          const featured = url.searchParams.get("featured");
          const search = url.searchParams.get("search");
          if (category) q = q.eq("category", category);
          if (featured === "1") q = q.eq("is_featured", true);
          if (search) q = q.or(`name.ilike.%${search}%,actor_id.ilike.%${search}%,description.ilike.%${search}%`);
          const { data, error } = await q.order("is_featured", { ascending: false }).order("name");
          if (error) return jsonError(error.message, 500);
          return json({ items: data });
        }

        if (resource === "favorites") {
          const uid = url.searchParams.get("telegram_user_id");
          let q = supabaseAdmin.from("apify_favorites").select("*").limit(limit);
          if (uid) q = q.eq("telegram_user_id", Number(uid));
          const { data, error } = await q.order("created_at", { ascending: false });
          if (error) return jsonError(error.message, 500);
          return json({ items: data });
        }

        if (resource === "runs") {
          const uid = url.searchParams.get("telegram_user_id");
          const status = url.searchParams.get("status");
          const since = url.searchParams.get("since");
          let q = supabaseAdmin.from("apify_runs").select("*").limit(limit);
          if (uid) q = q.eq("telegram_user_id", Number(uid));
          if (status) q = q.eq("status", status);
          if (since) q = q.gte("started_at", since);
          const { data, error } = await q.order("started_at", { ascending: false });
          if (error) return jsonError(error.message, 500);
          return json({ items: data });
        }

        // templates
        const uid = url.searchParams.get("telegram_user_id");
        let q = supabaseAdmin.from("apify_templates").select("*").limit(limit);
        if (uid) q = q.eq("telegram_user_id", Number(uid));
        const { data, error } = await q.order("created_at", { ascending: false });
        if (error) return jsonError(error.message, 500);
        return json({ items: data });
      },

      POST: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const url = new URL(request.url);
        const resource = resourceOf(url);
        if (!resource) return jsonError("unknown resource");
        const body = (await request.json()) as Record<string, unknown>;
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const db = supabaseAdmin as any;

        if (resource === "actors" || resource === "favorites") {
          const conflict = resource === "actors" ? "actor_id" : "telegram_user_id,actor_id";
          const { data, error } = await db
            .from(TABLE[resource])
            .upsert(body as any, { onConflict: conflict })
            .select()
            .single();
          if (error) return jsonError(error.message, 500);
          return json({ item: data });
        }

        const { data, error } = await db
          .from(TABLE[resource])
          .insert(body as any)
          .select()
          .single();
        if (error) return jsonError(error.message, 500);
        return json({ item: data });
      },

      PATCH: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const url = new URL(request.url);
        const resource = resourceOf(url);
        if (!resource) return jsonError("unknown resource");
        const body = (await request.json()) as Record<string, unknown> & { id?: string; run_id?: string };
        const { id, run_id, ...patch } = body;
        if (!id && !run_id) return jsonError("id or run_id required");
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        let q = (supabaseAdmin as any).from(TABLE[resource]).update(patch as any);
        q = id ? q.eq("id", id) : q.eq("run_id", run_id!);
        const { data, error } = await q.select().maybeSingle();
        if (error) return jsonError(error.message, 500);
        return json({ item: data });
      },

      DELETE: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const url = new URL(request.url);
        const resource = resourceOf(url);
        if (!resource) return jsonError("unknown resource");
        const id = url.searchParams.get("id");
        const actorId = url.searchParams.get("actor_id");
        const uid = url.searchParams.get("telegram_user_id");
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        let q = (supabaseAdmin as any).from(TABLE[resource]).delete();
        if (id) q = q.eq("id", id);
        else if (actorId) {
          q = q.eq("actor_id", actorId);
          if (uid) q = q.eq("telegram_user_id", Number(uid));
        } else return jsonError("id or actor_id required");
        const { error } = await q;
        if (error) return jsonError(error.message, 500);
        return json({ ok: true });
      },
    },
  },
});

import { createFileRoute } from "@tanstack/react-router";
import { checkBotToken, json, jsonError } from "@/lib/bot-auth";

/**
 * Generic Contact Validation Engine endpoint.
 *
 * GET  ?contact_type=phone&validator=whatsapp&values=213555...,213666...
 *      -> { cached: { [value]: { status, result, checked_at, expires_at } }, missing: [values not cached] }
 *
 * POST { validator, contact_type, ttl_days?, items: [{ contact_value, status, result?, error_message?, source_search_id? }] }
 *      -> { upserted: N }
 *
 * status must be one of: pending | running | valid | invalid | cached | error
 */
export const Route = createFileRoute("/api/public/bot/validations")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const url = new URL(request.url);
        const contact_type = url.searchParams.get("contact_type") ?? "phone";
        const validator = url.searchParams.get("validator");
        const valuesRaw = url.searchParams.get("values") ?? "";
        if (!validator) return jsonError("validator required");
        const values = valuesRaw.split(",").map((v) => v.trim()).filter(Boolean);
        if (values.length === 0) return json({ cached: {}, missing: [] });

        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const nowIso = new Date().toISOString();
        const { data, error } = await supabaseAdmin
          .from("contact_validations")
          .select("contact_value, status, result, checked_at, expires_at")
          .eq("contact_type", contact_type)
          .eq("validator", validator)
          .in("contact_value", values)
          .in("status", ["valid", "invalid", "cached"]);
        if (error) return jsonError(error.message, 500);

        const cached: Record<string, any> = {};
        for (const row of data ?? []) {
          if (row.expires_at && row.expires_at < nowIso) continue;
          cached[row.contact_value] = row;
        }
        const missing = values.filter((v) => !cached[v]);
        return json({ cached, missing });
      },

      POST: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const body = (await request.json()) as {
          validator: string;
          contact_type?: string;
          ttl_days?: number;
          items: Array<{
            contact_value: string;
            status: "pending" | "running" | "valid" | "invalid" | "cached" | "error";
            result?: Record<string, unknown>;
            error_message?: string;
            source_search_id?: string | null;
          }>;
        };
        if (!body.validator || !Array.isArray(body.items)) return jsonError("validator and items required");
        const contact_type = body.contact_type ?? "phone";
        const ttlDays = body.ttl_days ?? 30;
        const now = new Date();
        const expires = new Date(now.getTime() + ttlDays * 24 * 3600 * 1000).toISOString();

        const rows = body.items
          .filter((i) => i.contact_value)
          .map((i) => ({
            contact_type,
            contact_value: i.contact_value,
            validator: body.validator,
            status: i.status,
            result: i.result ?? {},
            error_message: i.error_message ?? null,
            checked_at: now.toISOString(),
            expires_at: i.status === "error" || i.status === "pending" || i.status === "running" ? null : expires,
            source_search_id: i.source_search_id ?? null,
            attempts: 1,
          }));

        if (rows.length === 0) return json({ upserted: 0 });

        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const { error } = await supabaseAdmin
          .from("contact_validations")
          .upsert(rows, { onConflict: "contact_type,contact_value,validator" });
        if (error) return jsonError(error.message, 500);

        // If this is a whatsapp validator, mirror the result onto extracted_numbers
        // for fast dashboard filters (has_whatsapp).
        // We rely on a generic result.on_whatsapp boolean (Apify whatsapp-checker output).
        if (body.validator === "whatsapp" && contact_type === "phone") {
          const valid = rows.filter((r) => r.status === "valid").map((r) => r.contact_value);
          const invalid = rows.filter((r) => r.status === "invalid").map((r) => r.contact_value);
          if (valid.length) {
            await supabaseAdmin.from("extracted_numbers").update({ notes: "whatsapp:valid" }).in("phone", valid).is("notes", null);
          }
          if (invalid.length) {
            await supabaseAdmin.from("extracted_numbers").update({ notes: "whatsapp:invalid" }).in("phone", invalid).is("notes", null);
          }
        }
        return json({ upserted: rows.length });
      },
    },
  },
});

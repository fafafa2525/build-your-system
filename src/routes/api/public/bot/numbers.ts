import { createFileRoute } from "@tanstack/react-router";
import { checkBotToken, json, jsonError } from "@/lib/bot-auth";

export const Route = createFileRoute("/api/public/bot/numbers")({
  server: {
    handlers: {
      // POST bulk upload extracted numbers for a search
      // body: { search_id, country, items: [{ phone, page_url?, page_name? }] }
      // Returns: { total, new_count, existing_count }
      POST: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const body = (await request.json()) as {
          search_id: string;
          country?: string;
          items: Array<{ phone: string; page_url?: string; page_name?: string }>;
        };
        if (!body.search_id || !Array.isArray(body.items)) return jsonError("search_id and items required");
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const now = new Date().toISOString();

        // Normalize + dedupe input
        const seen = new Set<string>();
        const cleanItems = body.items
          .map((i) => ({ ...i, phone: normalizePhone(i.phone) }))
          .filter((i) => i.phone && !seen.has(i.phone) && (seen.add(i.phone), true));

        if (cleanItems.length === 0) return json({ total: 0, new_count: 0, existing_count: 0 });

        // Find existing
        const phones = cleanItems.map((i) => i.phone);
        const { data: existing } = await supabaseAdmin
          .from("extracted_numbers")
          .select("id, phone, times_found")
          .in("phone", phones);
        const existingMap = new Map((existing ?? []).map((e: any) => [e.phone, e]));

        const toInsert: any[] = [];
        const toUpdate: Array<{ id: string; times_found: number }> = [];
        const junction: Array<{ search_id: string; number_id: string; is_new_at_time: boolean }> = [];
        const insertPhones: string[] = [];

        for (const it of cleanItems) {
          const ex = existingMap.get(it.phone);
          if (ex) {
            toUpdate.push({ id: ex.id, times_found: (ex.times_found ?? 1) + 1 });
            junction.push({ search_id: body.search_id, number_id: ex.id, is_new_at_time: false });
          } else {
            insertPhones.push(it.phone);
            toInsert.push({
              phone: it.phone,
              country: body.country ?? null,
              times_found: 1,
              first_seen_at: now,
              last_seen_at: now,
              first_search_id: body.search_id,
              last_search_id: body.search_id,
              page_url: it.page_url ?? null,
              page_name: it.page_name ?? null,
            });
          }
        }

        let newIds: string[] = [];
        if (toInsert.length > 0) {
          const { data: ins, error: insErr } = await supabaseAdmin
            .from("extracted_numbers")
            .insert(toInsert)
            .select("id, phone");
          if (insErr) return jsonError(insErr.message, 500);
          newIds = (ins ?? []).map((r: any) => r.id);
          for (const r of ins ?? []) {
            junction.push({ search_id: body.search_id, number_id: r.id, is_new_at_time: true });
          }
        }

        // Bulk update times_found for existing
        for (const u of toUpdate) {
          await supabaseAdmin
            .from("extracted_numbers")
            .update({ times_found: u.times_found, last_seen_at: now, last_search_id: body.search_id })
            .eq("id", u.id);
        }

        // Insert junction (ignore conflicts)
        if (junction.length > 0) {
          await supabaseAdmin.from("search_numbers").upsert(junction, { onConflict: "search_id,number_id" });
        }

        return json({
          total: cleanItems.length,
          new_count: newIds.length,
          existing_count: toUpdate.length,
          new_phones: insertPhones,
        });
      },
    },
  },
});

function normalizePhone(raw: string): string {
  if (!raw) return "";
  let s = raw.replace(/[\s\-()+]/g, "");
  if (s.startsWith("00")) s = s.slice(2);
  // Only keep digits
  s = s.replace(/[^\d]/g, "");
  return s;
}

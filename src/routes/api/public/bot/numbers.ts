import { createFileRoute } from "@tanstack/react-router";
import { checkBotToken, json, jsonError } from "@/lib/bot-auth";

export const Route = createFileRoute("/api/public/bot/numbers")({
  server: {
    handlers: {
      // GET recent numbers, optionally filtered by telegram_user_id (from their last search)
      // v2: fixed handler registration
      GET: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const url = new URL(request.url);
        const tgUid = url.searchParams.get("telegram_user_id");
        console.log(`[numbers GET] telegram_user_id=${tgUid}`);
        const limit = Math.min(Number(url.searchParams.get("limit") ?? 500), 2000);
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        let searchIds: string[] | null = null;
        if (tgUid) {
          const { data: s } = await supabaseAdmin
            .from("searches")
            .select("id")
            .eq("telegram_user_id", Number(tgUid))
            .eq("status", "completed")
            .order("finished_at", { ascending: false })
            .limit(1);
          if (!s || s.length === 0) return json({ items: [] });
          searchIds = s.map((r: any) => r.id);
        }
        let q = supabaseAdmin
          .from("extracted_numbers")
          .select("phone, country, page_url, page_name, kind, last_search_id, sources, business_name, category, city, rating, reviews_count, google_maps_url, website, email, claim_this_business")
          .order("last_seen_at", { ascending: false })
          .limit(limit);
        if (searchIds) q = q.in("last_search_id", searchIds);
        const { data, error } = await q;
        if (error) return jsonError(error.message, 500);
        console.log(`[numbers GET] returning ${(data ?? []).length} items`);
        return json({ items: data ?? [] });
      },

      // POST bulk upload extracted numbers for a search
      // body: { search_id, country, source?, items: [ ...number/business fields ] }
      POST: async ({ request }) => {
        const err = checkBotToken(request);
        if (err) return err;
        const body = (await request.json()) as {
          search_id: string;
          country?: string;
          source?: string; // "facebook" | "gmaps" | ...
          items: Array<{
            phone: string;
            kind?: string;
            page_url?: string;
            page_name?: string;
            has_store?: boolean;
            website?: string;
            business_name?: string;
            category?: string;
            address?: string;
            city?: string;
            rating?: number;
            reviews_count?: number;
            latitude?: number;
            longitude?: number;
            google_maps_url?: string;
          }>;
        };
        if (!body.search_id || !Array.isArray(body.items)) return jsonError("search_id and items required");
        const source = body.source || "facebook";
        const { supabaseAdmin } = await import("@/integrations/supabase/client.server");
        const now = new Date().toISOString();

        // Normalize + dedupe input by phone
        const seen = new Set<string>();
        const cleanItems = body.items
          .map((i) => ({ ...i, phone: normalizePhone(i.phone) }))
          .filter((i) => i.phone && !seen.has(i.phone) && (seen.add(i.phone), true));

        if (cleanItems.length === 0) return json({ total: 0, new_count: 0, existing_count: 0 });

        const phones = cleanItems.map((i) => i.phone);
        const { data: existing } = await supabaseAdmin
          .from("extracted_numbers")
          .select("id, phone, times_found, sources, business_name, category, address, city, rating, reviews_count, latitude, longitude, google_maps_url, website, page_url, page_name")
          .in("phone", phones);
        const existingMap = new Map((existing ?? []).map((e: any) => [e.phone, e]));

        const toInsert: any[] = [];
        const toUpdate: Array<{ id: string; patch: Record<string, any> }> = [];
        const junction: Array<{ search_id: string; number_id: string; is_new_at_time: boolean }> = [];
        const insertPhones: string[] = [];

        for (const it of cleanItems) {
          const ex: any = existingMap.get(it.phone);
          if (ex) {
            const sources: string[] = Array.isArray(ex.sources) ? ex.sources : [];
            const mergedSources = sources.includes(source) ? sources : [...sources, source];
            // Fill only missing fields (don't overwrite existing data with weaker data)
            const patch: Record<string, any> = {
              times_found: (ex.times_found ?? 1) + 1,
              last_seen_at: now,
              last_search_id: body.search_id,
              sources: mergedSources,
            };
            const fillIfEmpty = (col: string, val: any) => {
              if (val !== undefined && val !== null && val !== "" && (ex[col] === null || ex[col] === undefined || ex[col] === "")) {
                patch[col] = val;
              }
            };
            fillIfEmpty("business_name", it.business_name ?? it.page_name);
            fillIfEmpty("category", it.category);
            fillIfEmpty("address", it.address);
            fillIfEmpty("city", it.city);
            fillIfEmpty("rating", it.rating);
            fillIfEmpty("reviews_count", it.reviews_count);
            fillIfEmpty("latitude", it.latitude);
            fillIfEmpty("longitude", it.longitude);
            fillIfEmpty("google_maps_url", it.google_maps_url);
            fillIfEmpty("website", it.website);
            fillIfEmpty("page_url", it.page_url);
            fillIfEmpty("page_name", it.page_name);
            toUpdate.push({ id: ex.id, patch });
            junction.push({ search_id: body.search_id, number_id: ex.id, is_new_at_time: false });
          } else {
            insertPhones.push(it.phone);
            toInsert.push({
              phone: it.phone,
              country: body.country ?? null,
              kind: it.kind ?? null,
              times_found: 1,
              first_seen_at: now,
              last_seen_at: now,
              first_search_id: body.search_id,
              last_search_id: body.search_id,
              page_url: it.page_url ?? null,
              page_name: it.page_name ?? it.business_name ?? null,
              website: it.website ?? null,
              has_website: !!it.website,
              sources: [source],
              business_name: it.business_name ?? null,
              category: it.category ?? null,
              address: it.address ?? null,
              city: it.city ?? null,
              rating: it.rating ?? null,
              reviews_count: it.reviews_count ?? null,
              latitude: it.latitude ?? null,
              longitude: it.longitude ?? null,
              google_maps_url: it.google_maps_url ?? null,
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

        for (const u of toUpdate) {
          await supabaseAdmin.from("extracted_numbers").update(u.patch as any).eq("id", u.id);
        }

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

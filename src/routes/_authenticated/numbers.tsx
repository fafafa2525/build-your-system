import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { supabase } from "@/integrations/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { countryName, formatNumber, formatRelative, COUNTRIES } from "@/lib/format";
import { useState, useMemo } from "react";
import { toast } from "sonner";
import { Download, Copy, Check, Trash2, ExternalLink, Star } from "lucide-react";

export const Route = createFileRoute("/_authenticated/numbers")({
  component: NumbersPage,
});

type Row = {
  id: string;
  phone: string;
  country: string | null;
  times_found: number;
  is_sent: boolean;
  last_seen_at: string;
  sources: string[] | null;
  business_name: string | null;
  category: string | null;
  city: string | null;
  rating: number | null;
  reviews_count: number | null;
  website: string | null;
  google_maps_url: string | null;
  page_url: string | null;
  page_name: string | null;
  kind: string | null;
};

function SourceBadge({ s }: { s: string }) {
  const map: Record<string, { label: string; className: string }> = {
    facebook: { label: "Facebook", className: "bg-blue-500/15 text-blue-500" },
    gmaps: { label: "Google Maps", className: "bg-emerald-500/15 text-emerald-500" },
    instagram: { label: "Instagram", className: "bg-pink-500/15 text-pink-500" },
    tiktok: { label: "TikTok", className: "bg-purple-500/15 text-purple-500" },
  };
  const info = map[s] ?? { label: s, className: "bg-muted text-muted-foreground" };
  return <Badge variant="secondary" className={info.className}>{info.label}</Badge>;
}

function NumbersPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [country, setCountry] = useState<string>("all");
  const [source, setSource] = useState<string>("all");
  const [city, setCity] = useState<string>("");
  const [category, setCategory] = useState<string>("");
  const [minRating, setMinRating] = useState<string>("0");
  const [hasWebsite, setHasWebsite] = useState(false);
  const [status, setStatus] = useState<string>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const numbers = useQuery({
    queryKey: ["numbers", country, status],
    queryFn: async () => {
      let q = supabase.from("extracted_numbers").select("*").order("last_seen_at", { ascending: false }).limit(2000);
      if (country !== "all") q = q.eq("country", country);
      if (status === "sent") q = q.eq("is_sent", true);
      if (status === "unsent") q = q.eq("is_sent", false);
      const { data, error } = await q;
      if (error) throw error;
      return data as unknown as Row[];
    },
  });

  const filtered = useMemo(() => {
    let out = numbers.data ?? [];
    if (search.trim()) {
      const s = search.trim().toLowerCase();
      out = out.filter((n) =>
        n.phone.includes(s) ||
        (n.business_name ?? "").toLowerCase().includes(s) ||
        (n.page_name ?? "").toLowerCase().includes(s),
      );
    }
    if (source !== "all") out = out.filter((n) => (n.sources ?? []).includes(source));
    if (city.trim()) out = out.filter((n) => (n.city ?? "").toLowerCase().includes(city.trim().toLowerCase()));
    if (category.trim()) out = out.filter((n) => (n.category ?? "").toLowerCase().includes(category.trim().toLowerCase()));
    const min = Number(minRating);
    if (min > 0) out = out.filter((n) => (n.rating ?? 0) >= min);
    if (hasWebsite) out = out.filter((n) => !!n.website);
    return out;
  }, [numbers.data, search, source, city, category, minRating, hasWebsite]);

  function toggle(id: string) {
    const n = new Set(selected);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    setSelected(n);
  }

  function toggleAll() {
    if (selected.size === filtered.length) setSelected(new Set());
    else setSelected(new Set(filtered.map((n) => n.id)));
  }

  const targetRows = () =>
    filtered.filter((n) => selected.size === 0 || selected.has(n.id));

  function copyAll() {
    const phones = targetRows().map((n) => n.phone);
    navigator.clipboard.writeText(phones.join("\n"));
    toast.success(`تم نسخ ${phones.length} رقم`);
  }

  function download(name: string, mime: string, body: string) {
    const blob = new Blob([body], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  }

  function exportCSV() {
    const rows = targetRows();
    const header = ["phone", "business_name", "category", "city", "country", "rating", "reviews", "website", "google_maps_url", "page_url", "sources"];
    const csvEscape = (v: any) => {
      const s = v == null ? "" : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [header.join(",")];
    for (const r of rows) {
      lines.push([
        r.phone, r.business_name ?? r.page_name ?? "", r.category ?? "", r.city ?? "", r.country ?? "",
        r.rating ?? "", r.reviews_count ?? "", r.website ?? "", r.google_maps_url ?? "", r.page_url ?? "",
        (r.sources ?? []).join("|"),
      ].map(csvEscape).join(","));
    }
    download(`leads-${new Date().toISOString().slice(0, 10)}.csv`, "text/csv", lines.join("\n"));
  }

  function exportTSV() {
    const rows = targetRows();
    const header = "phone\tbusiness_name\tcategory\tcity\tcountry\trating\treviews\twebsite\tgoogle_maps_url\tpage_url\tsources\n";
    const body = rows.map((r) =>
      [r.phone, r.business_name ?? r.page_name ?? "", r.category ?? "", r.city ?? "", r.country ?? "",
        r.rating ?? "", r.reviews_count ?? "", r.website ?? "", r.google_maps_url ?? "", r.page_url ?? "",
        (r.sources ?? []).join("|")].map((v) => String(v).replace(/\t/g, " ")).join("\t"),
    ).join("\n");
    download(`leads-${new Date().toISOString().slice(0, 10)}.tsv`, "text/tab-separated-values", header + body);
  }

  function exportVCF() {
    const rows = targetRows();
    const vcf = rows.map((r, i) => {
      const name = r.business_name ?? r.page_name ?? `Lead ${i + 1}`;
      return [
        "BEGIN:VCARD",
        "VERSION:3.0",
        `FN:${name}`,
        `TEL;TYPE=CELL:${r.phone}`,
        r.website ? `URL:${r.website}` : "",
        r.address ? `ADR:;;${(r as any).address};${r.city ?? ""};;;${r.country ?? ""}` : "",
        r.category ? `NOTE:${r.category}${r.rating ? ` — ⭐${r.rating}` : ""}` : "",
        "END:VCARD",
      ].filter(Boolean).join("\n");
    }).join("\n\n");
    download(`leads-${new Date().toISOString().slice(0, 10)}.vcf`, "text/vcard", vcf);
  }

  async function markSent() {
    if (selected.size === 0) return toast.error("اختر أرقاماً أولاً");
    const { error } = await supabase
      .from("extracted_numbers")
      .update({ is_sent: true, sent_at: new Date().toISOString() })
      .in("id", Array.from(selected));
    if (error) return toast.error(error.message);
    toast.success(`تم تعليم ${selected.size} كمُرسل`);
    setSelected(new Set());
    qc.invalidateQueries({ queryKey: ["numbers"] });
  }

  async function delSelected() {
    if (selected.size === 0) return;
    if (!confirm(`حذف ${selected.size} رقم؟`)) return;
    const { error } = await supabase.from("extracted_numbers").delete().in("id", Array.from(selected));
    if (error) return toast.error(error.message);
    toast.success("تم الحذف");
    setSelected(new Set());
    qc.invalidateQueries({ queryKey: ["numbers"] });
  }

  return (
    <div className="p-4 md:p-8 space-y-4 max-w-7xl mx-auto">
      <div>
        <h1 className="text-2xl md:text-3xl font-bold">قاعدة العملاء المحتملين (Leads)</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {formatNumber(filtered.length)} من أصل {formatNumber(numbers.data?.length ?? 0)}
        </p>
      </div>

      <Card>
        <CardContent className="pt-6 space-y-3">
          <div className="grid gap-2 md:grid-cols-4">
            <Input placeholder="بحث (رقم، اسم نشاط...)" value={search} onChange={(e) => setSearch(e.target.value)} />
            <Select value={country} onValueChange={setCountry}>
              <SelectTrigger><SelectValue placeholder="الدولة" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">كل الدول</SelectItem>
                {COUNTRIES.map((c) => <SelectItem key={c.code} value={c.code}>{c.nameAr}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={source} onValueChange={setSource}>
              <SelectTrigger><SelectValue placeholder="المصدر" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">كل المصادر</SelectItem>
                <SelectItem value="facebook">Facebook</SelectItem>
                <SelectItem value="gmaps">Google Maps</SelectItem>
              </SelectContent>
            </Select>
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger><SelectValue placeholder="الحالة" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">الكل</SelectItem>
                <SelectItem value="unsent">لم يُرسل</SelectItem>
                <SelectItem value="sent">أُرسل</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2 md:grid-cols-4">
            <Input placeholder="المدينة" value={city} onChange={(e) => setCity(e.target.value)} />
            <Input placeholder="نوع النشاط" value={category} onChange={(e) => setCategory(e.target.value)} />
            <Select value={minRating} onValueChange={setMinRating}>
              <SelectTrigger><SelectValue placeholder="أدنى تقييم" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="0">أي تقييم</SelectItem>
                <SelectItem value="3">⭐ 3+</SelectItem>
                <SelectItem value="4">⭐ 4+</SelectItem>
                <SelectItem value="4.5">⭐ 4.5+</SelectItem>
              </SelectContent>
            </Select>
            <label className="flex items-center gap-2 text-sm px-3 rounded-md border border-border">
              <Checkbox checked={hasWebsite} onCheckedChange={(v) => setHasWebsite(!!v)} />
              يوجد موقع إلكتروني
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={copyAll}>
              <Copy className="w-4 h-4 ml-1" /> نسخ الأرقام
            </Button>
            <Button variant="secondary" size="sm" onClick={exportCSV}>
              <Download className="w-4 h-4 ml-1" /> CSV
            </Button>
            <Button variant="secondary" size="sm" onClick={exportTSV}>
              <Download className="w-4 h-4 ml-1" /> TSV
            </Button>
            <Button variant="secondary" size="sm" onClick={exportVCF}>
              <Download className="w-4 h-4 ml-1" /> VCF
            </Button>
          </div>
          {selected.size > 0 && (
            <div className="flex flex-wrap items-center gap-2 p-2 rounded-lg bg-primary/10">
              <span className="text-sm">اختير {selected.size}</span>
              <Button size="sm" variant="secondary" onClick={markSent}>
                <Check className="w-4 h-4 ml-1" /> تعليم كمُرسل
              </Button>
              <Button size="sm" variant="destructive" onClick={delSelected}>
                <Trash2 className="w-4 h-4 ml-1" /> حذف
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
                إلغاء
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox
                    checked={filtered.length > 0 && selected.size === filtered.length}
                    onCheckedChange={toggleAll}
                  />
                </TableHead>
                <TableHead>النشاط</TableHead>
                <TableHead>الرقم</TableHead>
                <TableHead>المدينة / الدولة</TableHead>
                <TableHead>التقييم</TableHead>
                <TableHead>موقع</TableHead>
                <TableHead>المصادر</TableHead>
                <TableHead>آخر ظهور</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((n) => (
                <TableRow key={n.id} className={selected.has(n.id) ? "bg-primary/5" : ""}>
                  <TableCell>
                    <Checkbox checked={selected.has(n.id)} onCheckedChange={() => toggle(n.id)} />
                  </TableCell>
                  <TableCell className="max-w-[220px]">
                    <div className="font-medium truncate">{n.business_name ?? n.page_name ?? "—"}</div>
                    {n.category && <div className="text-xs text-muted-foreground truncate">{n.category}</div>}
                  </TableCell>
                  <TableCell className="font-mono" dir="ltr">{n.phone}</TableCell>
                  <TableCell className="text-sm">
                    {n.city && <div>{n.city}</div>}
                    <div className="text-xs text-muted-foreground">{countryName(n.country ?? "")}</div>
                  </TableCell>
                  <TableCell>
                    {n.rating != null ? (
                      <div className="flex items-center gap-1 text-sm">
                        <Star className="w-3.5 h-3.5 fill-yellow-500 text-yellow-500" />
                        {n.rating}
                        {n.reviews_count != null && (
                          <span className="text-xs text-muted-foreground">({n.reviews_count})</span>
                        )}
                      </div>
                    ) : "—"}
                  </TableCell>
                  <TableCell>
                    {n.website ? (
                      <a href={n.website} target="_blank" rel="noreferrer" className="text-primary text-sm inline-flex items-center gap-1">
                        <ExternalLink className="w-3 h-3" /> فتح
                      </a>
                    ) : "—"}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {(n.sources ?? []).map((s) => <SourceBadge key={s} s={s} />)}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{formatRelative(n.last_seen_at)}</TableCell>
                </TableRow>
              ))}
              {filtered.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-muted-foreground py-8">لا توجد نتائج</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

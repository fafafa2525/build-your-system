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
import { Download, Copy, Check, Trash2 } from "lucide-react";

export const Route = createFileRoute("/_authenticated/numbers")({
  component: NumbersPage,
});

function NumbersPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [country, setCountry] = useState<string>("all");
  const [status, setStatus] = useState<string>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const numbers = useQuery({
    queryKey: ["numbers", country, status],
    queryFn: async () => {
      let q = supabase.from("extracted_numbers").select("*").order("last_seen_at", { ascending: false }).limit(1000);
      if (country !== "all") q = q.eq("country", country);
      if (status === "sent") q = q.eq("is_sent", true);
      if (status === "unsent") q = q.eq("is_sent", false);
      const { data, error } = await q;
      if (error) throw error;
      return data;
    },
  });

  const filtered = useMemo(() => {
    if (!numbers.data) return [];
    if (!search.trim()) return numbers.data;
    return numbers.data.filter((n: any) => n.phone.includes(search));
  }, [numbers.data, search]);

  function toggle(id: string) {
    const n = new Set(selected);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    setSelected(n);
  }

  function toggleAll() {
    if (selected.size === filtered.length) setSelected(new Set());
    else setSelected(new Set(filtered.map((n: any) => n.id)));
  }

  function copyAll() {
    const phones = filtered.filter((n: any) => selected.size === 0 || selected.has(n.id)).map((n: any) => n.phone);
    navigator.clipboard.writeText(phones.join("\n"));
    toast.success(`تم نسخ ${phones.length} رقم`);
  }

  function exportTxt() {
    const phones = filtered.filter((n: any) => selected.size === 0 || selected.has(n.id)).map((n: any) => n.phone);
    const blob = new Blob([phones.join("\n")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `numbers-${new Date().toISOString().split("T")[0]}.txt`;
    a.click();
    URL.revokeObjectURL(url);
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
        <h1 className="text-2xl md:text-3xl font-bold">الأرقام المستخرجة</h1>
        <p className="text-sm text-muted-foreground mt-1">{formatNumber(filtered.length)} رقم</p>
      </div>

      <Card>
        <CardContent className="pt-6 space-y-3">
          <div className="grid gap-2 md:grid-cols-4">
            <Input placeholder="بحث رقم..." value={search} onChange={(e) => setSearch(e.target.value)} dir="ltr" />
            <Select value={country} onValueChange={setCountry}>
              <SelectTrigger><SelectValue placeholder="الدولة" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">كل الدول</SelectItem>
                {COUNTRIES.map((c) => <SelectItem key={c.code} value={c.code}>{c.nameAr}</SelectItem>)}
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
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" onClick={copyAll} className="flex-1">
                <Copy className="w-4 h-4 ml-1" /> نسخ
              </Button>
              <Button variant="secondary" size="sm" onClick={exportTxt} className="flex-1">
                <Download className="w-4 h-4 ml-1" /> تصدير
              </Button>
            </div>
          </div>
          {selected.size > 0 && (
            <div className="flex items-center gap-2 p-2 rounded-lg bg-primary/10">
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
                <TableHead>الرقم</TableHead>
                <TableHead>الدولة</TableHead>
                <TableHead>ظهر</TableHead>
                <TableHead>الحالة</TableHead>
                <TableHead>آخر ظهور</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((n: any) => (
                <TableRow key={n.id} className={selected.has(n.id) ? "bg-primary/5" : ""}>
                  <TableCell>
                    <Checkbox checked={selected.has(n.id)} onCheckedChange={() => toggle(n.id)} />
                  </TableCell>
                  <TableCell className="font-mono" dir="ltr">{n.phone}</TableCell>
                  <TableCell>{countryName(n.country)}</TableCell>
                  <TableCell>{n.times_found}×</TableCell>
                  <TableCell>
                    {n.is_sent ? (
                      <Badge variant="secondary" className="bg-success/20 text-success">مُرسل</Badge>
                    ) : (
                      <Badge variant="secondary">جديد</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{formatRelative(n.last_seen_at)}</TableCell>
                </TableRow>
              ))}
              {filtered.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-8">لا توجد أرقام</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

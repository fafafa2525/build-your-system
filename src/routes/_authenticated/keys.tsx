import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { supabase } from "@/integrations/supabase/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatNumber, formatRelative } from "@/lib/format";
import { useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Power, PowerOff, KeyRound } from "lucide-react";

export const Route = createFileRoute("/_authenticated/keys")({
  component: KeysPage,
});

function KeysPage() {
  const qc = useQueryClient();
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(false);

  const keys = useQuery({
    queryKey: ["apify-keys"],
    refetchInterval: 5000,
    queryFn: async () => {
      const { data, error } = await supabase.from("apify_keys").select("*").order("created_at", { ascending: false });
      if (error) throw error;
      return data;
    },
  });

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!apiKey.startsWith("apify_api_")) {
      return toast.error("مفتاح Apify يجب أن يبدأ بـ apify_api_");
    }
    setLoading(true);
    const { error } = await supabase.from("apify_keys").insert({
      label: label || `مفتاح ${(keys.data?.length ?? 0) + 1}`,
      api_key: apiKey.trim(),
      status: "active",
    });
    setLoading(false);
    if (error) return toast.error(error.message);
    toast.success("تم إضافة المفتاح");
    setLabel("");
    setApiKey("");
    qc.invalidateQueries({ queryKey: ["apify-keys"] });
  }

  async function toggleStatus(id: string, current: string) {
    const next = current === "active" ? "disabled" : "active";
    const { error } = await supabase.from("apify_keys").update({ status: next }).eq("id", id);
    if (error) return toast.error(error.message);
    qc.invalidateQueries({ queryKey: ["apify-keys"] });
  }

  async function del(id: string) {
    if (!confirm("حذف هذا المفتاح؟")) return;
    const { error } = await supabase.from("apify_keys").delete().eq("id", id);
    if (error) return toast.error(error.message);
    toast.success("تم الحذف");
    qc.invalidateQueries({ queryKey: ["apify-keys"] });
  }

  async function delExhausted() {
    const count = keys.data?.filter((k: any) => k.status === "exhausted").length ?? 0;
    if (!count) return toast.info("لا توجد مفاتيح منتهية");
    if (!confirm(`حذف ${count} مفتاح منتهي؟`)) return;
    const { error } = await supabase.from("apify_keys").delete().eq("status", "exhausted");
    if (error) return toast.error(error.message);
    toast.success(`تم حذف ${count} مفتاح`);
    qc.invalidateQueries({ queryKey: ["apify-keys"] });
  }

  async function reactivate(id: string) {
    const { error } = await supabase.from("apify_keys")
      .update({ status: "active", last_error: null }).eq("id", id);
    if (error) return toast.error(error.message);
    toast.success("تم إعادة التفعيل");
    qc.invalidateQueries({ queryKey: ["apify-keys"] });
  }

  const active = keys.data?.filter((k: any) => k.status === "active").length ?? 0;
  const exhausted = keys.data?.filter((k: any) => k.status === "exhausted").length ?? 0;

  return (
    <div className="p-4 md:p-8 space-y-4 max-w-7xl mx-auto">
      <div>
        <h1 className="text-2xl md:text-3xl font-bold">مفاتيح Apify</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {active} نشط • {exhausted} منتهي • البوت ينتقل تلقائياً للمفتاح التالي عند انتهاء الحالي
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base flex items-center gap-2"><Plus className="w-4 h-4" /> إضافة مفتاح جديد</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={add} className="grid gap-3 md:grid-cols-[1fr_2fr_auto]">
            <div className="space-y-1.5">
              <Label>اسم (اختياري)</Label>
              <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="مثال: حساب 1" />
            </div>
            <div className="space-y-1.5">
              <Label>مفتاح Apify</Label>
              <Input value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="apify_api_..." dir="ltr" required />
            </div>
            <div className="flex items-end">
              <Button type="submit" disabled={loading}>إضافة</Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>الاسم</TableHead>
                <TableHead>المفتاح</TableHead>
                <TableHead>الحالة</TableHead>
                <TableHead>الاستخدام</TableHead>
                <TableHead>اليومي</TableHead>
                <TableHead>آخر استخدام</TableHead>
                <TableHead>آخر خطأ</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.data?.map((k: any) => (
                <TableRow key={k.id}>
                  <TableCell className="font-medium">
                    <div className="flex items-center gap-2">
                      <KeyRound className="w-4 h-4 text-muted-foreground" />
                      {k.label}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground" dir="ltr">
                    {k.api_key.slice(0, 14)}...{k.api_key.slice(-4)}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={k.status} />
                  </TableCell>
                  <TableCell>{formatNumber(k.usage_count)}</TableCell>
                  <TableCell>{formatNumber(k.daily_usage)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{formatRelative(k.last_used_at)}</TableCell>
                  <TableCell className="text-xs text-destructive max-w-[200px] truncate">{k.last_error ?? "—"}</TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" onClick={() => toggleStatus(k.id, k.status)}>
                        {k.status === "active" ? <PowerOff className="w-4 h-4" /> : <Power className="w-4 h-4" />}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => del(k.id)}>
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {keys.data?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                    لا توجد مفاتيح. أضف أول مفتاح لبدء التشغيل.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active: "bg-success/20 text-success",
    exhausted: "bg-warning/20 text-warning",
    disabled: "bg-muted text-muted-foreground",
    error: "bg-destructive/20 text-destructive",
  };
  const labels: Record<string, string> = {
    active: "نشط",
    exhausted: "منتهي",
    disabled: "معطل",
    error: "خطأ",
  };
  return <Badge variant="secondary" className={map[status]}>{labels[status] ?? status}</Badge>;
}

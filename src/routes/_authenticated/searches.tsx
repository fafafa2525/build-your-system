import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { supabase } from "@/integrations/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { countryName, formatDateTime, formatNumber, formatRelative } from "@/lib/format";
import { useState } from "react";
import { Activity, CheckCircle2, AlertCircle, Clock, Trash2, Eye } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/_authenticated/searches")({
  component: SearchesPage,
});

function SearchesPage() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const searches = useQuery({
    queryKey: ["searches-all"],
    refetchInterval: 4000,
    queryFn: async () => {
      const { data, error } = await supabase
        .from("searches")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(200);
      if (error) throw error;
      return data;
    },
  });

  async function del(id: string) {
    if (!confirm("حذف هذا البحث وكل سجلاته؟")) return;
    const { error } = await supabase.from("searches").delete().eq("id", id);
    if (error) return toast.error(error.message);
    toast.success("تم الحذف");
    qc.invalidateQueries({ queryKey: ["searches-all"] });
  }

  return (
    <div className="p-4 md:p-8 space-y-4 max-w-7xl mx-auto">
      <div>
        <h1 className="text-2xl md:text-3xl font-bold">عمليات البحث</h1>
        <p className="text-sm text-muted-foreground mt-1">سجل كامل لكل مهام الاستخراج</p>
      </div>
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>الكلمة</TableHead>
                <TableHead>الدولة</TableHead>
                <TableHead>الحالة</TableHead>
                <TableHead>الصفحات</TableHead>
                <TableHead>الأرقام</TableHead>
                <TableHead>جديد</TableHead>
                <TableHead>المدة</TableHead>
                <TableHead>التاريخ</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {searches.data?.map((s: any) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium max-w-[200px] truncate">{s.keyword}</TableCell>
                  <TableCell>{countryName(s.country)}</TableCell>
                  <TableCell>
                    <StatusBadge status={s.status} />
                    {s.status === "running" && <Progress value={s.progress} className="h-1 mt-1 w-24" />}
                  </TableCell>
                  <TableCell>{formatNumber(s.pages_found)}</TableCell>
                  <TableCell className="font-semibold">{formatNumber(s.numbers_found)}</TableCell>
                  <TableCell className="text-success">{formatNumber(s.numbers_new)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {s.duration_seconds ? `${s.duration_seconds}ث` : "—"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{formatRelative(s.created_at)}</TableCell>
                  <TableCell>
                    <div className="flex gap-1 justify-end">
                      <Button size="sm" variant="ghost" onClick={() => setSelectedId(s.id)}>
                        <Eye className="w-4 h-4" />
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => del(s.id)}>
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {searches.data?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={9} className="text-center text-muted-foreground py-8">
                    لا توجد عمليات بحث بعد
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <SearchDetail id={selectedId} onClose={() => setSelectedId(null)} />
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; className: string; icon: any }> = {
    pending: { label: "بانتظار", className: "bg-muted text-muted-foreground", icon: Clock },
    running: { label: "يعمل", className: "bg-chart-2/20 text-chart-2", icon: Activity },
    completed: { label: "مكتمل", className: "bg-success/20 text-success", icon: CheckCircle2 },
    failed: { label: "فشل", className: "bg-destructive/20 text-destructive", icon: AlertCircle },
    cancelled: { label: "ملغى", className: "bg-muted text-muted-foreground", icon: AlertCircle },
  };
  const it = map[status] ?? map.pending;
  const Icon = it.icon;
  return (
    <Badge variant="secondary" className={it.className}>
      <Icon className="w-3 h-3 ml-1" />
      {it.label}
    </Badge>
  );
}

function SearchDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const detail = useQuery({
    queryKey: ["search-detail", id],
    enabled: !!id,
    refetchInterval: 3000,
    queryFn: async () => {
      if (!id) return null;
      const [search, logs, numbers] = await Promise.all([
        supabase.from("searches").select("*").eq("id", id).single(),
        supabase.from("job_logs").select("*").eq("search_id", id).order("created_at", { ascending: false }).limit(100),
        supabase.from("search_numbers").select("number_id, extracted_numbers(*)").eq("search_id", id).limit(500),
      ]);
      return { search: search.data, logs: logs.data ?? [], numbers: numbers.data ?? [] };
    },
  });

  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="left" className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{detail.data?.search?.keyword ?? "..."}</SheetTitle>
        </SheetHeader>
        {detail.data?.search && (
          <div className="mt-4 space-y-4">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <InfoRow label="الدولة" value={countryName(detail.data.search.country)} />
              <InfoRow label="الحالة" value={<StatusBadge status={detail.data.search.status} />} />
              <InfoRow label="الصفحات" value={formatNumber(detail.data.search.pages_found)} />
              <InfoRow label="الأرقام" value={formatNumber(detail.data.search.numbers_found)} />
              <InfoRow label="أرقام جديدة" value={formatNumber(detail.data.search.numbers_new)} />
              <InfoRow label="المدة" value={detail.data.search.duration_seconds ? `${detail.data.search.duration_seconds} ثانية` : "—"} />
              <InfoRow label="بدأ" value={formatDateTime(detail.data.search.started_at)} />
              <InfoRow label="انتهى" value={formatDateTime(detail.data.search.finished_at)} />
            </div>
            {detail.data.search.error_message && (
              <div className="p-3 rounded-lg bg-destructive/10 text-destructive text-sm">
                {detail.data.search.error_message}
              </div>
            )}
            {detail.data.search.status === "running" && (
              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span>{detail.data.search.progress_message ?? "جاري..."}</span>
                  <span>{detail.data.search.progress}%</span>
                </div>
                <Progress value={detail.data.search.progress} />
              </div>
            )}
            <div>
              <h3 className="font-semibold text-sm mb-2">السجل ({detail.data.logs.length})</h3>
              <div className="space-y-1 max-h-64 overflow-y-auto bg-muted/30 rounded-lg p-2 font-mono text-xs" dir="ltr">
                {detail.data.logs.map((l: any) => (
                  <div key={l.id} className="flex gap-2">
                    <span className="text-muted-foreground shrink-0">{new Date(l.created_at).toLocaleTimeString()}</span>
                    <span
                      className={
                        l.level === "error"
                          ? "text-destructive"
                          : l.level === "warn"
                          ? "text-warning"
                          : "text-foreground"
                      }
                    >
                      [{l.level}]
                    </span>
                    <span className="break-all">{l.message}</span>
                  </div>
                ))}
                {detail.data.logs.length === 0 && (
                  <div className="text-muted-foreground text-center py-4">لا يوجد سجل</div>
                )}
              </div>
            </div>
            {detail.data.numbers.length > 0 && (
              <div>
                <h3 className="font-semibold text-sm mb-2">الأرقام ({detail.data.numbers.length})</h3>
                <div className="max-h-64 overflow-y-auto bg-muted/30 rounded-lg p-2 font-mono text-xs space-y-0.5" dir="ltr">
                  {detail.data.numbers.map((n: any) => (
                    <div key={n.number_id}>{n.extracted_numbers?.phone}</div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function InfoRow({ label, value }: { label: string; value: any }) {
  return (
    <div className="p-2 rounded bg-muted/30">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5">{value}</div>
    </div>
  );
}

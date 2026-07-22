import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { supabase } from "@/integrations/supabase/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { COUNTRIES, countryName, formatNumber, formatRelative } from "@/lib/format";
import { useState } from "react";
import { toast } from "sonner";
import {
  Activity,
  Phone,
  KeyRound,
  Search as SearchIcon,
  Plus,
  Server,
  Radio,
  Cpu,
  CheckCircle2,
  AlertCircle,
  Clock,
} from "lucide-react";

export const Route = createFileRoute("/_authenticated/dashboard")({
  component: Dashboard,
});

function Dashboard() {
  const stats = useQuery({
    queryKey: ["dashboard-stats"],
    refetchInterval: 5000,
    queryFn: async () => {
      const [numbers, keys, running, today, health, recent] = await Promise.all([
        supabase.from("extracted_numbers").select("id", { count: "exact", head: true }),
        supabase.from("apify_keys").select("id, status", { count: "exact" }).eq("status", "active"),
        supabase.from("searches").select("id", { count: "exact", head: true }).in("status", ["pending", "running"]),
        supabase
          .from("extracted_numbers")
          .select("id", { count: "exact", head: true })
          .gte("created_at", new Date(Date.now() - 86400000).toISOString()),
        supabase.from("health_status").select("*"),
        supabase
          .from("searches")
          .select("*")
          .order("created_at", { ascending: false })
          .limit(6),
      ]);
      return {
        totalNumbers: numbers.count ?? 0,
        activeKeys: keys.count ?? 0,
        runningJobs: running.count ?? 0,
        numbersToday: today.count ?? 0,
        health: health.data ?? [],
        recent: recent.data ?? [],
      };
    },
  });

  return (
    <div className="p-4 md:p-8 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold">لوحة التحكم</h1>
          <p className="text-sm text-muted-foreground mt-1">نظرة عامة على النظام</p>
        </div>
        <NewSearchDialog />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="إجمالي الأرقام" value={formatNumber(stats.data?.totalNumbers)} icon={Phone} tone="primary" />
        <StatCard label="أرقام اليوم" value={formatNumber(stats.data?.numbersToday)} icon={Activity} tone="chart" />
        <StatCard label="مفاتيح نشطة" value={formatNumber(stats.data?.activeKeys)} icon={KeyRound} tone="warning" />
        <StatCard label="مهام قيد التشغيل" value={formatNumber(stats.data?.runningJobs)} icon={SearchIcon} tone="success" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">آخر عمليات البحث</CardTitle>
            <Link to="/searches" className="text-xs text-primary hover:underline">
              عرض الكل ←
            </Link>
          </CardHeader>
          <CardContent>
            {stats.data?.recent.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-sm">
                لا توجد عمليات بحث بعد. ابدأ ببحث جديد.
              </div>
            ) : (
              <div className="space-y-2">
                {stats.data?.recent.map((s: any) => (
                  <Link
                    to="/searches"
                    key={s.id}
                    className="flex items-center justify-between p-3 rounded-lg border border-border hover:bg-accent/50 transition-colors"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="font-medium truncate">{s.keyword}</div>
                      <div className="text-xs text-muted-foreground flex items-center gap-2 mt-0.5">
                        <span>{countryName(s.country)}</span>
                        <span>•</span>
                        <span>{formatRelative(s.created_at)}</span>
                        {s.numbers_found > 0 && (
                          <>
                            <span>•</span>
                            <span>{formatNumber(s.numbers_found)} رقم</span>
                          </>
                        )}
                      </div>
                      {s.status === "running" && (
                        <Progress value={s.progress} className="h-1 mt-2" />
                      )}
                    </div>
                    <StatusBadge status={s.status} />
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">حالة النظام</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {(stats.data?.health ?? []).map((h: any) => (
              <HealthRow key={h.service} service={h.service} status={h.status} lastHeartbeat={h.last_heartbeat} />
            ))}
            {(stats.data?.health ?? []).length === 0 && (
              <div className="text-xs text-muted-foreground">في انتظار أول heartbeat من الـ VPS...</div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatCard({ label, value, icon: Icon, tone }: { label: string; value: string; icon: any; tone: string }) {
  const toneMap: Record<string, string> = {
    primary: "text-primary bg-primary/10",
    chart: "text-chart-2 bg-chart-2/10",
    warning: "text-warning bg-warning/10",
    success: "text-success bg-success/10",
  };
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm text-muted-foreground">{label}</div>
            <div className="text-2xl font-bold mt-1">{value}</div>
          </div>
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${toneMap[tone]}`}>
            <Icon className="w-5 h-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; className: string; icon: any }> = {
    pending: { label: "بانتظار", className: "bg-muted text-muted-foreground", icon: Clock },
    running: { label: "قيد التشغيل", className: "bg-chart-2/20 text-chart-2", icon: Activity },
    completed: { label: "مكتمل", className: "bg-success/20 text-success", icon: CheckCircle2 },
    failed: { label: "فشل", className: "bg-destructive/20 text-destructive", icon: AlertCircle },
    cancelled: { label: "ملغى", className: "bg-muted text-muted-foreground", icon: AlertCircle },
  };
  const it = map[status] ?? map.pending;
  const Icon = it.icon;
  return (
    <Badge variant="secondary" className={`${it.className} shrink-0`}>
      <Icon className="w-3 h-3 ml-1" />
      {it.label}
    </Badge>
  );
}

function HealthRow({ service, status, lastHeartbeat }: any) {
  const isOnline = status === "online" && lastHeartbeat && Date.now() - new Date(lastHeartbeat).getTime() < 120000;
  const iconMap: Record<string, any> = { vps: Server, telegram_bot: Radio, apify: Cpu };
  const labelMap: Record<string, string> = { vps: "خادم VPS", telegram_bot: "بوت تلجرام", apify: "خدمة Apify" };
  const Icon = iconMap[service] ?? Server;
  return (
    <div className="flex items-center justify-between p-2 rounded-lg bg-muted/40">
      <div className="flex items-center gap-2">
        <Icon className="w-4 h-4 text-muted-foreground" />
        <span className="text-sm">{labelMap[service] ?? service}</span>
      </div>
      <div className="flex items-center gap-2">
        <div className={`w-2 h-2 rounded-full ${isOnline ? "bg-success animate-pulse" : "bg-destructive"}`} />
        <span className="text-xs text-muted-foreground">{isOnline ? "متصل" : "غير متصل"}</span>
      </div>
    </div>
  );
}

function NewSearchDialog() {
  const [open, setOpen] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [country, setCountry] = useState("DZ");
  const [maxPages, setMaxPages] = useState(100);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    const { error } = await supabase.from("searches").insert({
      keyword,
      country,
      max_pages: maxPages,
      status: "pending",
      source: "web",
    });
    setLoading(false);
    if (error) return toast.error(error.message);
    toast.success("تم إنشاء المهمة — سيلتقطها الـ Worker خلال ثوانٍ");
    setOpen(false);
    setKeyword("");
  }

  if (!open) {
    return (
      <Button onClick={() => setOpen(true)}>
        <Plus className="w-4 h-4 ml-2" />
        بحث جديد
      </Button>
    );
  }

  return (
    <Card className="w-full lg:w-auto lg:min-w-[400px]">
      <CardHeader>
        <CardTitle className="text-base">إنشاء بحث جديد</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-3">
          <div className="space-y-1.5">
            <Label>الكلمة المفتاحية</Label>
            <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} required placeholder="مثال: مطاعم، سيارات، أزياء..." />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1.5">
              <Label>الدولة</Label>
              <Select value={country} onValueChange={setCountry}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {COUNTRIES.map((c) => (
                    <SelectItem key={c.code} value={c.code}>{c.nameAr}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>عدد الصفحات كحد أقصى</Label>
              <Input type="number" min={10} max={500} value={maxPages} onChange={(e) => setMaxPages(parseInt(e.target.value))} />
            </div>
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={loading} className="flex-1">
              {loading ? "..." : "بدء البحث"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>إلغاء</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

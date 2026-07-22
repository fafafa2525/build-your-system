import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { supabase } from "@/integrations/supabase/client";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { Copy, Server, Terminal } from "lucide-react";
import { COUNTRIES } from "@/lib/format";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export const Route = createFileRoute("/_authenticated/settings")({
  component: SettingsPage,
});

function SettingsPage() {
  const qc = useQueryClient();
  const [tgIds, setTgIds] = useState("");
  const [defaultCountry, setDefaultCountry] = useState("DZ");
  const [defaultMaxPages, setDefaultMaxPages] = useState(100);
  const [autoSend, setAutoSend] = useState(true);

  const settings = useQuery({
    queryKey: ["bot-settings"],
    queryFn: async () => {
      const { data, error } = await supabase.from("bot_settings").select("*").eq("id", 1).single();
      if (error) throw error;
      return data;
    },
  });

  useEffect(() => {
    if (settings.data) {
      setTgIds((settings.data.allowed_telegram_ids ?? []).join("\n"));
      setDefaultCountry(settings.data.default_country ?? "DZ");
      setDefaultMaxPages(settings.data.default_max_pages ?? 100);
      setAutoSend(settings.data.auto_send_results ?? true);
    }
  }, [settings.data]);

  async function save() {
    const ids = tgIds
      .split(/[\s,\n]+/)
      .map((s) => s.trim())
      .filter(Boolean)
      .map(Number)
      .filter((n) => !isNaN(n));
    const { error } = await supabase
      .from("bot_settings")
      .update({
        allowed_telegram_ids: ids,
        default_country: defaultCountry,
        default_max_pages: defaultMaxPages,
        auto_send_results: autoSend,
      })
      .eq("id", 1);
    if (error) return toast.error(error.message);
    toast.success("تم الحفظ");
    qc.invalidateQueries({ queryKey: ["bot-settings"] });
  }

  const apiBase = typeof window !== "undefined" ? window.location.origin : "";

  function copy(text: string) {
    navigator.clipboard.writeText(text);
    toast.success("نُسخ");
  }

  return (
    <div className="p-4 md:p-8 space-y-4 max-w-4xl mx-auto">
      <div>
        <h1 className="text-2xl md:text-3xl font-bold">الإعدادات</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">إعدادات البوت</CardTitle>
          <CardDescription>من يستطيع استخدام بوت تلجرام وإعدادات البحث الافتراضية</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>معرفات تلجرام المسموح لها (Telegram User IDs)</Label>
            <Textarea
              value={tgIds}
              onChange={(e) => setTgIds(e.target.value)}
              placeholder="مثال:&#10;123456789&#10;987654321"
              rows={4}
              dir="ltr"
            />
            <p className="text-xs text-muted-foreground">
              رقم واحد في كل سطر. احصل على ID الخاص بك من @userinfobot في تلجرام.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label>الدولة الافتراضية</Label>
              <Select value={defaultCountry} onValueChange={setDefaultCountry}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {COUNTRIES.map((c) => <SelectItem key={c.code} value={c.code}>{c.nameAr}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>عدد الصفحات الافتراضي</Label>
              <Input type="number" value={defaultMaxPages} onChange={(e) => setDefaultMaxPages(parseInt(e.target.value))} />
            </div>
          </div>
          <div className="flex items-center justify-between p-3 rounded-lg bg-muted/40">
            <div>
              <Label>إرسال النتائج تلقائياً</Label>
              <p className="text-xs text-muted-foreground mt-0.5">أرسل الأرقام كملف عبر تلجرام فور اكتمال البحث</p>
            </div>
            <Switch checked={autoSend} onCheckedChange={setAutoSend} />
          </div>
          <Button onClick={save}>حفظ الإعدادات</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Server className="w-4 h-4" /> إعداد VPS
          </CardTitle>
          <CardDescription>هذه القيم تحتاجها عند نشر البوت على خادمك</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ConfigRow label="LOVABLE_API_URL" value={apiBase} onCopy={() => copy(apiBase)} />
          <ConfigRow
            label="BOT_API_TOKEN"
            value="•••••••• (محفوظ سرياً)"
            note="التوكن السري بين VPS والواجهة — احصل عليه من إعدادات المشروع → Secrets"
          />
          <div className="p-4 rounded-lg bg-muted/30 border border-border">
            <div className="flex items-center gap-2 mb-2">
              <Terminal className="w-4 h-4" />
              <span className="font-semibold text-sm">خطوات النشر السريع على VPS</span>
              <Badge variant="secondary" className="text-xs">Ubuntu / Debian</Badge>
            </div>
            <pre className="text-xs bg-background/60 rounded p-3 overflow-x-auto font-mono leading-relaxed" dir="ltr">
{`# 1. نسخ ملفات المشروع
scp -r ./vps user@YOUR_VPS:/opt/adsbot

# 2. الاتصال بالـ VPS
ssh user@YOUR_VPS
cd /opt/adsbot

# 3. تنصيب المتطلبات
sudo apt update && sudo apt install -y python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. إعداد المتغيرات
cp .env.example .env
nano .env   # املأ TELEGRAM_BOT_TOKEN و LOVABLE_API_URL و BOT_API_TOKEN

# 5. اختبار
python bot.py

# 6. تشغيل دائم مع systemd
sudo cp systemd/adsbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now adsbot
sudo systemctl status adsbot`}
            </pre>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function ConfigRow({ label, value, onCopy, note }: { label: string; value: string; onCopy?: () => void; note?: string }) {
  return (
    <div>
      <Label>{label}</Label>
      <div className="flex gap-2 mt-1.5">
        <Input value={value} readOnly dir="ltr" className="font-mono text-xs" />
        {onCopy && (
          <Button variant="secondary" size="icon" onClick={onCopy}>
            <Copy className="w-4 h-4" />
          </Button>
        )}
      </div>
      {note && <p className="text-xs text-muted-foreground mt-1">{note}</p>}
    </div>
  );
}

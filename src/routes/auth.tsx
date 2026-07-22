import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import { Radar } from "lucide-react";

export const Route = createFileRoute("/auth")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "تسجيل الدخول — AdsBot" },
      { name: "description", content: "تسجيل الدخول إلى لوحة تحكم AdsBot لإدارة استخراج الأرقام." },
    ],
  }),
  component: AuthPage,
});

function AuthPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (data.user) navigate({ to: "/dashboard" });
    });
  }, [navigate]);

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (error) return toast.error(error.message);
    toast.success("تم تسجيل الدخول");
    navigate({ to: "/dashboard" });
  }

  async function signUp(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: window.location.origin },
    });
    setLoading(false);
    if (error) return toast.error(error.message);
    toast.success("تم إنشاء الحساب — يمكنك تسجيل الدخول الآن");
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4 relative overflow-hidden">
      <div className="absolute inset-0 opacity-30 pointer-events-none"
        style={{ background: "radial-gradient(circle at 20% 20%, oklch(0.35 0.15 150) 0%, transparent 40%), radial-gradient(circle at 80% 80%, oklch(0.30 0.12 220) 0%, transparent 45%)" }} />
      <Card className="w-full max-w-md relative z-10 border-border/60 backdrop-blur">
        <CardHeader className="text-center space-y-3">
          <div className="mx-auto w-14 h-14 rounded-2xl bg-primary/15 flex items-center justify-center">
            <Radar className="w-7 h-7 text-primary" />
          </div>
          <CardTitle className="text-2xl font-bold">AdsBot</CardTitle>
          <CardDescription>لوحة تحكم استخراج أرقام واتساب من إعلانات فيسبوك</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="signin">
            <TabsList className="grid grid-cols-2 w-full">
              <TabsTrigger value="signin">دخول</TabsTrigger>
              <TabsTrigger value="signup">حساب جديد</TabsTrigger>
            </TabsList>
            <TabsContent value="signin" className="mt-4">
              <form onSubmit={signIn} className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="email">البريد الإلكتروني</Label>
                  <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} dir="ltr" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password">كلمة السر</Label>
                  <Input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} dir="ltr" />
                </div>
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? "جاري..." : "تسجيل الدخول"}
                </Button>
              </form>
            </TabsContent>
            <TabsContent value="signup" className="mt-4">
              <form onSubmit={signUp} className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="email2">البريد الإلكتروني</Label>
                  <Input id="email2" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} dir="ltr" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password2">كلمة السر (6 أحرف على الأقل)</Label>
                  <Input id="password2" type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} dir="ltr" />
                </div>
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? "جاري..." : "إنشاء الحساب"}
                </Button>
                <p className="text-xs text-muted-foreground text-center">
                  أول حساب يُسجَّل يحصل تلقائياً على صلاحيات المدير.
                </p>
              </form>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}

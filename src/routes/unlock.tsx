import { createFileRoute, useRouter, useSearch } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useState } from "react";
import { Lock, Radar } from "lucide-react";
import { unlockDashboard } from "@/lib/gate.functions";

type Search = { redirect?: string };

export const Route = createFileRoute("/unlock")({
  validateSearch: (search: Record<string, unknown>): Search => ({
    redirect: typeof search.redirect === "string" ? search.redirect : undefined,
  }),
  head: () => ({
    meta: [
      { title: "دخول محمي — AdsBot" },
      { name: "description", content: "أدخل الرمز السري للوصول إلى لوحة تحكم AdsBot." },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: UnlockPage,
});

function UnlockPage() {
  const router = useRouter();
  const search = useSearch({ from: "/unlock" });
  const unlock = useServerFn(unlockDashboard);
  const [pin, setPin] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(false);
    setLoading(true);
    try {
      const res = await unlock({ data: { pin } });
      if (res.ok) {
        const to = search.redirect && search.redirect.startsWith("/") ? search.redirect : "/dashboard";
        await router.navigate({ to, replace: true });
        router.invalidate();
      } else {
        setError(true);
        setPin("");
      }
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4" dir="rtl">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-primary/15 flex items-center justify-center mb-3">
            <Radar className="w-7 h-7 text-primary" />
          </div>
          <h1 className="text-2xl font-bold">AdsBot</h1>
          <p className="text-sm text-muted-foreground mt-1">أدخل الرمز السري للمتابعة</p>
        </div>

        <form onSubmit={onSubmit} className="bg-card border border-border rounded-2xl p-6 shadow-sm space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 flex items-center gap-2">
              <Lock className="w-4 h-4" />
              الرمز السري
            </label>
            <input
              type="password"
              inputMode="text"
              autoFocus
              value={pin}
              onChange={(e) => setPin(e.target.value)}
              className="w-full h-11 px-3 rounded-lg bg-background border border-input text-center tracking-widest text-lg focus:outline-none focus:ring-2 focus:ring-primary"
              placeholder="••••"
              disabled={loading}
            />
          </div>

          {error && (
            <div className="text-sm text-destructive text-center bg-destructive/10 rounded-lg py-2">
              رمز غير صحيح، حاول مرة أخرى
            </div>
          )}

          <button
            type="submit"
            disabled={loading || pin.length === 0}
            className="w-full h-11 rounded-lg bg-primary text-primary-foreground font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {loading ? "جارٍ الدخول..." : "دخول"}
          </button>
        </form>

        <p className="text-xs text-muted-foreground text-center mt-6">
          الوصول محمي بالرمز السري المخزّن في إعدادات المشروع
        </p>
      </div>
    </div>
  );
}

import { createFileRoute, Outlet, Link, useRouterState, useRouter, redirect } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import {
  Radar,
  LayoutDashboard,
  Phone,
  KeyRound,
  Settings,
  History,
  LogOut,
} from "lucide-react";
import { isUnlocked, lockDashboard } from "@/lib/gate.functions";

export const Route = createFileRoute("/_authenticated")({
  ssr: false,
  beforeLoad: async ({ location }) => {
    const res = await isUnlocked();
    if (!res.unlocked) {
      throw redirect({ to: "/unlock", search: { redirect: location.href } });
    }
  },
  component: AuthShell,
});

const NAV = [
  { to: "/dashboard", label: "لوحة التحكم", icon: LayoutDashboard },
  { to: "/searches", label: "عمليات البحث", icon: History },
  { to: "/numbers", label: "الأرقام", icon: Phone },
  { to: "/keys", label: "مفاتيح Apify", icon: KeyRound },
  { to: "/settings", label: "الإعدادات", icon: Settings },
] as const;

function AuthShell() {
  const path = useRouterState({ select: (s) => s.location.pathname });


  return (
    <div className="min-h-screen bg-background flex">
      <aside className="hidden md:flex w-64 shrink-0 border-l border-border bg-sidebar text-sidebar-foreground flex-col">
        <div className="p-5 border-b border-sidebar-border flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-primary/15 flex items-center justify-center">
            <Radar className="w-5 h-5 text-primary" />
          </div>
          <div>
            <div className="font-bold text-lg">AdsBot</div>
            <div className="text-xs text-muted-foreground">لوحة التحكم</div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {NAV.map((item) => {
            const active = path.startsWith(item.to);
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  active
                    ? "bg-sidebar-primary/15 text-sidebar-primary"
                    : "text-sidebar-foreground hover:bg-sidebar-accent"
                }`}
              >
                <Icon className="w-4 h-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      <main className="flex-1 overflow-x-hidden">
        {/* Mobile header */}
        <div className="md:hidden sticky top-0 z-30 bg-background/95 backdrop-blur border-b border-border p-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Radar className="w-5 h-5 text-primary" />
            <span className="font-bold">AdsBot</span>
          </div>
        </div>

        <div className="md:hidden border-b border-border overflow-x-auto flex">
          {NAV.map((item) => {
            const active = path.startsWith(item.to);
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`flex items-center gap-2 px-4 py-3 text-sm shrink-0 border-b-2 ${
                  active ? "border-primary text-primary" : "border-transparent text-muted-foreground"
                }`}
              >
                <Icon className="w-4 h-4" />
                {item.label}
              </Link>
            );
          })}
        </div>
        <Outlet />
      </main>
    </div>
  );
}

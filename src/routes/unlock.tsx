import { createFileRoute, redirect } from "@tanstack/react-router";

type Search = { redirect?: string };

export const Route = createFileRoute("/unlock")({
  validateSearch: (search: Record<string, unknown>): Search => ({
    redirect: typeof search.redirect === "string" ? search.redirect : undefined,
  }),
  beforeLoad: ({ search }) => {
    throw redirect({
      to: search.redirect && search.redirect.startsWith("/") ? search.redirect : "/dashboard",
      replace: true,
    });
  },
  head: () => ({
    meta: [
      { title: "تحويل — AdsBot" },
      { name: "description", content: "تحويل تلقائي إلى لوحة تحكم AdsBot." },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: () => null,
});

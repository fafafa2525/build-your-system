/**
 * Central constants shared across UI.
 */
export const COUNTRIES: { code: string; name: string; nameAr: string; dialCode: string }[] = [
  { code: "DZ", name: "Algeria", nameAr: "الجزائر", dialCode: "213" },
  { code: "MA", name: "Morocco", nameAr: "المغرب", dialCode: "212" },
  { code: "TN", name: "Tunisia", nameAr: "تونس", dialCode: "216" },
  { code: "EG", name: "Egypt", nameAr: "مصر", dialCode: "20" },
  { code: "SA", name: "Saudi Arabia", nameAr: "السعودية", dialCode: "966" },
  { code: "AE", name: "UAE", nameAr: "الإمارات", dialCode: "971" },
  { code: "KW", name: "Kuwait", nameAr: "الكويت", dialCode: "965" },
  { code: "QA", name: "Qatar", nameAr: "قطر", dialCode: "974" },
  { code: "BH", name: "Bahrain", nameAr: "البحرين", dialCode: "973" },
  { code: "OM", name: "Oman", nameAr: "عمان", dialCode: "968" },
  { code: "JO", name: "Jordan", nameAr: "الأردن", dialCode: "962" },
  { code: "LB", name: "Lebanon", nameAr: "لبنان", dialCode: "961" },
  { code: "IQ", name: "Iraq", nameAr: "العراق", dialCode: "964" },
  { code: "SY", name: "Syria", nameAr: "سوريا", dialCode: "963" },
  { code: "YE", name: "Yemen", nameAr: "اليمن", dialCode: "967" },
  { code: "LY", name: "Libya", nameAr: "ليبيا", dialCode: "218" },
  { code: "SD", name: "Sudan", nameAr: "السودان", dialCode: "249" },
  { code: "FR", name: "France", nameAr: "فرنسا", dialCode: "33" },
  { code: "US", name: "United States", nameAr: "الولايات المتحدة", dialCode: "1" },
  { code: "GB", name: "United Kingdom", nameAr: "المملكة المتحدة", dialCode: "44" },
  { code: "TR", name: "Turkey", nameAr: "تركيا", dialCode: "90" },
];

export function countryName(code: string | null | undefined): string {
  if (!code) return "—";
  const c = COUNTRIES.find((x) => x.code === code);
  return c ? c.nameAr : code;
}

export function formatNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return "0";
  return new Intl.NumberFormat("ar-EG").format(n);
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diff = Math.floor((now - then) / 1000);
  if (diff < 60) return `منذ ${diff} ث`;
  if (diff < 3600) return `منذ ${Math.floor(diff / 60)} د`;
  if (diff < 86400) return `منذ ${Math.floor(diff / 3600)} س`;
  if (diff < 604800) return `منذ ${Math.floor(diff / 86400)} يوم`;
  return new Date(iso).toLocaleDateString("ar-EG");
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ar-EG", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

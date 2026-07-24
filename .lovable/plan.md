# خطة المرحلة 2 — Google Maps + Source Providers Architecture

الفكرة: تحويل النظام من "بوت فيسبوك" إلى منصة Lead Generation متعددة المصادر، وGoogle Maps هو أول مصدر جديد مبني على نفس البنية (Jobs، Keys، Numbers، Validator، Export). لا يتم كسر أي ميزة حالية.

## 1) تعديلات قاعدة البيانات (Migration واحدة)

- `searches`: إضافة أعمدة `provider TEXT NOT NULL DEFAULT 'facebook'`, `city TEXT`, `category TEXT` (تُستخدم لـ gmaps؛ facebook يتجاهلها).
- `extracted_numbers`: إضافة `sources TEXT[] DEFAULT ARRAY['facebook']` (مصفوفة مصادر — للـ dedup عبر المصادر)، وحقول أعمال Google Maps:
  `business_name`, `category`, `address`, `city`, `rating NUMERIC`, `reviews_count INT`, `latitude NUMERIC`, `longitude NUMERIC`, `google_maps_url`.
- جميع الأعمدة nullable لعدم كسر البيانات الحالية. تحديث بيانات ما قبل الترحيل: تعبئة `sources` بالقيمة `{facebook}` تلقائياً.
- Backfill: `UPDATE searches SET provider='facebook' WHERE provider IS NULL;`

## 2) بنية Source Providers (Backend)

ملف جديد `src/lib/providers/types.ts` يعرّف واجهة `SourceProvider`:
```
{ id, label, requiredFields: string[], jobDefaults }
```
تسجيل خفيف في `src/lib/providers/index.ts` (facebook + gmaps الآن، وسهل إضافة instagram/tiktok لاحقاً).

على الـ VPS، ملف `vps/providers/base.py` يحدد واجهة `Provider.run(job, key, progress_cb) -> list[ExtractedItem]`. ثم:
- `vps/providers/facebook.py` — يلفّ الكود الحالي (Ads Library + Pages Scraper).
- `vps/providers/gmaps.py` — يستدعي `compass/crawler-google-places` عبر نفس `call_actor_with_rotation` (نفس نظام المفاتيح، نفس exhausted detection، نفس logs).

`process_job` في `bot.py` يختار الـ provider حسب `job['provider']`، ويستخدم نفس الـ heartbeat/log_job/update_job/upload path.

## 3) أمر البوت `/gmaps`

`ConversationHandler` جديد بثلاث حالات: نوع النشاط → المدينة → الدولة (زر inline من نفس قائمة COUNTRIES). يُنشئ job عبر نفس endpoint `POST /api/public/bot/jobs` مع `provider: "gmaps"`, `category`, `city`, `country`. يستقبل نفس تحديثات التقدم الحية.

## 4) الـ API layer

- `POST /api/public/bot/jobs`: قبول `provider`, `city`, `category` (اختيارية). نفس الـ rate limit اليومي.
- `POST /api/public/bot/numbers`: قبول حقول Google Maps الجديدة و`source` (`facebook`|`gmaps`). عند وجود الرقم مسبقاً: `sources = array_append_unique`، ودمج الحقول الفارغة فقط (لا نكتب فوق بيانات فيسبوك ببيانات ناقصة، والعكس).
- لا endpoint جديد للـ validator — نفس `/validate` يعمل كما هو لأن الأرقام كلها في نفس الجدول.

## 5) Dashboard

صفحة جديدة `src/routes/_authenticated/leads.tsx` (بديل موحّد ل `numbers.tsx` لاحقاً لكن نُبقي القديم عاملاً):
- جدول: النشاط، المدينة، التقييم، عدد المراجعات، الهاتف، الموقع، ✅ واتساب؟، المصادر (chips).
- فلاتر: الدولة، المدينة، النشاط، الحد الأدنى للتقييم، وجود موقع، وجود واتساب، المصدر.
- زر تصدير: TSV / CSV / VCF (نفس شكل التصدير الحالي مع أعمدة إضافية).

تعديل بسيط في القائمة الجانبية لإضافة رابط "Leads".

## 6) نقاط الجودة

- لا نلمس ملفات auto-gen (`client.ts`, `client.server.ts`, `types.ts`) — التحديث سيأتي بعد قبول الـ migration.
- تعامل مع أخطاء Apify بنفس آلية rotation.
- Logs بالعربي عبر `log_job` كما هو الحال حالياً.
- Backward compatible: أي job قديم بدون `provider` يُعامل كـ `facebook`.

## 7) الخطوات (بالترتيب)

1. Migration للأعمدة الجديدة.
2. تحديث الـ API endpoints (jobs + numbers).
3. بنية providers على VPS + `/gmaps` command.
4. صفحة Leads + الفلاتر + التصدير.
5. توثيق النشر للـ VPS في نفس ملف `vps/README.md`.

## Technical

- Actor المستخدم: `compass/crawler-google-places` (الأكثر استقراراً لـ Google Maps). Input: `{ searchStringsArray: ["<category> in <city>, <country>"], maxCrawledPlaces, language }`.
- Deduplication: طبيعة الجدول تبقى phone-based (unique). المصادر تُدمج في مصفوفة، والحقول الوصفية تُملأ فقط إذا كانت `NULL`.
- `sources` array بدل جدول junction جديد لتبسيط الاستعلامات في الـ Dashboard.

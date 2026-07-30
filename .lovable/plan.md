# تحويل AdsBot إلى منصة Apify كاملة

## الفكرة المعمارية

```text
Layer 1 — Apify Platform  (إدارة كاملة: Actors, Runs, Datasets, Storage, Usage, Keys)
        ▲ يستدعيها
Layer 2 — Business Providers (Meta Ads / Google Maps / TikTok ...)
        = Workflows جاهزة تستخدم Actors من الطبقة الأولى
```

كود الطبقة الأولى في مجلد جديد `vps/apify_platform/`، والطبقة الثانية في `vps/providers/`. `bot.py` يبقى فقط: التشغيل + القائمة الرئيسية + التوجيه.

## القائمة الرئيسية الجديدة

```text
🎯 استخراج العملاء        ⚙️ منصة Apify
   Meta Ads                  📦 Actors      🔎 Discover
   Google Maps               ⭐ Featured    ❤️ Favorites
   TikTok / Instagram        🕘 Recent      📂 Categories
   ✅ فحص واتساب             ▶️ Running Jobs 📊 Usage
                             💰 Balance     🔑 API Keys
                             📄 Datasets    🧹 Storage
                             📥 Imports     📤 Exports
                             🤖 Templates
```

كل شاشة = قائمة أزرار مع تنقّل (رجوع / القائمة الرئيسية) وترقيم صفحات موحّد.

## المراحل

### المرحلة 1 — الأساس (Registry + التنقّل)
- جداول جديدة في قاعدة البيانات:
  - `apify_actors` — actors المسجّلة في النظام (id, actor_id, name, description, category, price_note, default_input, is_featured, is_builtin)
  - `apify_favorites` — مفضّلات المستخدم
  - `apify_runs` — سجل التشغيلات (run_id, actor_id, status, items, cost, dataset_id, started/finished, telegram_user_id)
  - `apify_templates` — تشغيلات جاهزة (name, actor_id, input JSON)
- API عامة تحت `src/routes/api/public/bot/apify/*` لقراءة/كتابة هذه الجداول.
- محرّك قوائم موحّد + شاشات: Actors، Categories، Favorites، Recent.
- بذر أوّلي لـ ~20 actor مشهور مصنّفة (Meta, Maps, TikTok, Instagram, LinkedIn, Amazon, Etsy, Reddit, Shopify, YouTube, Email, Phone...).

### المرحلة 2 — Discover + Imports + Featured
- بحث حي في متجر Apify مع صفحات نتائج وبطاقة تفصيلية لكل actor (وصف، سعر، مدخلات، آخر تشغيل، Run، إضافة للمفضّلة).
- Imports: لصق رابط `https://apify.com/<user>/<actor>` فيُسجَّل في النظام.
- Featured: قوائم مختارة (الأفضل/الأرخص/الأسرع/لاستخراج العملاء).

### المرحلة 3 — التشغيل والمتابعة
- Running Jobs: عرض حسب الحالة (Running/Pending/Succeeded/Failed/Aborted) مع Cancel / Retry / Open Result.
- تشغيل غير محجوب مع تحديث تقدّم داخل الرسالة، وتسجيل كل تشغيل في `apify_runs`.
- Templates: حفظ أي إدخال كقالب وإعادة تشغيله بضغطة.

### المرحلة 4 — البيانات والحساب
- Datasets: عرض، تحميل، حذف، إعادة تشغيل من نفس المدخلات.
- Storage: Key-Value Stores، Request Queues، حجم التخزين.
- Usage: عدد التشغيلات، تكلفة يوم/أسبوع/شهر، عدد النتائج، متوسط الزمن.
- Balance: رصيد Apify والاستهلاك اليومي عبر `/users/me` و`/users/me/usage/monthly`.
- API Keys: نقل الإدارة الكاملة (إضافة/تعطيل/حذف/تدوير) إلى نفس القسم.

### المرحلة 5 — Exports وطبقة Providers
- تصدير موحّد: CSV / Excel / JSON / TSV (Google Sheets لاحقاً عبر Connector).
- إعادة كتابة Meta Ads و Google Maps كـ Providers تستدعي Actors من الـ Registry بدل تثبيت الـ actor id داخل الكود — فأي تحديث للـ actor يتم من الواجهة لا من الكود.

## تفاصيل تقنية
- كل الاستدعاءات تمر عبر `ApifyClient` مع تدوير المفاتيح الحالي (اكتشاف الرصيد المنتهي → المفتاح التالي).
- حالة الشاشات في `context.user_data` مع callback data مضغوطة (`ap:<screen>:<arg>`) لتفادي حد 64 بايت.
- الواجهة الويب تبقى للمراقبة؛ الأولوية للبوت.

## البدء
سأبدأ فوراً بالمرحلة 1 (الجداول + التنقّل + Registry + البذر)، ثم أتابع المراحل بالترتيب.

-- Apify Platform layer: actor registry, favorites, runs, templates

CREATE TABLE public.apify_actors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id text NOT NULL UNIQUE,
  name text NOT NULL,
  description text,
  category text NOT NULL DEFAULT 'other',
  price_note text,
  default_input jsonb NOT NULL DEFAULT '{}'::jsonb,
  is_featured boolean NOT NULL DEFAULT false,
  is_builtin boolean NOT NULL DEFAULT false,
  tags text[] NOT NULL DEFAULT '{}',
  last_run_at timestamptz,
  run_count integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.apify_actors TO anon, authenticated;
GRANT ALL ON public.apify_actors TO service_role;
ALTER TABLE public.apify_actors ENABLE ROW LEVEL SECURITY;
CREATE POLICY public_all ON public.apify_actors FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);

CREATE TABLE public.apify_favorites (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  telegram_user_id bigint,
  actor_id text NOT NULL,
  name text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (telegram_user_id, actor_id)
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.apify_favorites TO anon, authenticated;
GRANT ALL ON public.apify_favorites TO service_role;
ALTER TABLE public.apify_favorites ENABLE ROW LEVEL SECURITY;
CREATE POLICY public_all ON public.apify_favorites FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);

CREATE TABLE public.apify_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id text,
  actor_id text NOT NULL,
  actor_name text,
  status text NOT NULL DEFAULT 'RUNNING',
  provider text,
  input jsonb,
  dataset_id text,
  items_count integer NOT NULL DEFAULT 0,
  cost_usd numeric,
  duration_seconds integer,
  error_message text,
  telegram_user_id bigint,
  telegram_chat_id bigint,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_apify_runs_started ON public.apify_runs (started_at DESC);
CREATE INDEX idx_apify_runs_user ON public.apify_runs (telegram_user_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.apify_runs TO anon, authenticated;
GRANT ALL ON public.apify_runs TO service_role;
ALTER TABLE public.apify_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY public_all ON public.apify_runs FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);

CREATE TABLE public.apify_templates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  actor_id text NOT NULL,
  input jsonb NOT NULL DEFAULT '{}'::jsonb,
  telegram_user_id bigint,
  use_count integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.apify_templates TO anon, authenticated;
GRANT ALL ON public.apify_templates TO service_role;
ALTER TABLE public.apify_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY public_all ON public.apify_templates FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);

-- Seed the built-in actor registry
INSERT INTO public.apify_actors (actor_id, name, description, category, price_note, default_input, is_featured, is_builtin, tags) VALUES
('curious_coder/facebook-ads-library-scraper','Meta Ads Library','سحب الإعلانات النشطة من مكتبة إعلانات فيسبوك','meta','~$2 / 1000 نتيجة','{"count":500}'::jsonb,true,true,'{meta,ads,leads}'),
('apify/facebook-pages-scraper','Facebook Pages','بيانات صفحات فيسبوك: هاتف، إيميل، موقع','meta','~$3 / 1000 صفحة','{}'::jsonb,true,true,'{meta,leads,phone}'),
('compass/crawler-google-places','Google Maps Places','أنشطة محلية مع الهاتف والموقع والتقييمات','maps','~$4 / 1000 مكان','{"maxCrawledPlacesPerSearch":100}'::jsonb,true,true,'{maps,google,leads,phone}'),
('compass/google-maps-reviews-scraper','Google Maps Reviews','تقييمات ومراجعات الأماكن','reviews','~$2 / 1000 مراجعة','{}'::jsonb,false,true,'{maps,reviews}'),
('maged120/whatsapp-number-checker','WhatsApp Checker','فحص إن كان الرقم مسجّلاً في واتساب','phone','~$1 / 1000 رقم','{}'::jsonb,true,true,'{phone,whatsapp,validation}'),
('clockworks/tiktok-scraper','TikTok Scraper','حسابات وفيديوهات ووصف الحسابات على تيك توك','tiktok','~$3 / 1000 نتيجة','{"resultsPerPage":100}'::jsonb,true,true,'{tiktok,social}'),
('clockworks/tiktok-profile-scraper','TikTok Profiles','بيانات الحسابات: bio، رابط، متابعون','tiktok','~$3 / 1000 حساب','{}'::jsonb,false,true,'{tiktok,social,leads}'),
('apify/instagram-scraper','Instagram Scraper','منشورات وحسابات إنستقرام','instagram','~$2.3 / 1000 نتيجة','{"resultsLimit":100}'::jsonb,true,true,'{instagram,social}'),
('apify/instagram-profile-scraper','Instagram Profiles','بيانات الحسابات التجارية مع الروابط','instagram','~$2.3 / 1000 حساب','{}'::jsonb,false,true,'{instagram,social,leads}'),
('apimaestro/linkedin-profile-detail','LinkedIn Profiles','بيانات ملفات لينكدإن','linkedin','~$5 / 1000 ملف','{}'::jsonb,false,true,'{linkedin,b2b,leads}'),
('bebity/linkedin-jobs-scraper','LinkedIn Jobs','وظائف لينكدإن — شركات توظّف الآن','jobs','~$5 / 1000 وظيفة','{}'::jsonb,false,true,'{linkedin,jobs,b2b}'),
('junglee/amazon-crawler','Amazon Products','منتجات وأسعار أمازون','ecommerce','~$3 / 1000 منتج','{}'::jsonb,false,true,'{amazon,ecommerce}'),
('epctex/etsy-scraper','Etsy Scraper','متاجر ومنتجات Etsy','ecommerce','~$5 / 1000 نتيجة','{}'::jsonb,false,true,'{etsy,ecommerce}'),
('trudax/reddit-scraper','Reddit Scraper','منشورات وتعليقات ريديت','social','~$2 / 1000 نتيجة','{}'::jsonb,false,true,'{reddit,social}'),
('epctex/shopify-scraper','Shopify Stores','متاجر Shopify ومنتجاتها','ecommerce','~$5 / 1000 نتيجة','{}'::jsonb,false,true,'{shopify,ecommerce,leads}'),
('streamers/youtube-scraper','YouTube Scraper','قنوات وفيديوهات يوتيوب','video','~$5 / 1000 نتيجة','{}'::jsonb,false,true,'{youtube,video,social}'),
('vdrmota/contact-info-scraper','Contact Info Scraper','استخراج الإيميل والهاتف والسوشيال من أي موقع','email','~$1 / 1000 صفحة','{}'::jsonb,true,true,'{email,phone,leads}'),
('apify/website-content-crawler','Website Crawler','زحف كامل لمحتوى المواقع','seo','~$1 / 1000 صفحة','{}'::jsonb,false,true,'{seo,crawler,ai}'),
('apify/google-search-scraper','Google Search','نتائج بحث جوجل SERP','seo','~$3 / 1000 نتيجة','{}'::jsonb,false,true,'{google,seo,serp}'),
('emastra/google-ads-transparency-scraper','Google Ads Transparency','معلنون نشطون على جوجل','google','~$4 / 1000 نتيجة','{}'::jsonb,true,true,'{google,ads,leads}'),
('apify/web-scraper','Web Scraper','سكرايبر عام قابل للبرمجة','monitoring','حسب الاستهلاك','{}'::jsonb,false,true,'{custom,crawler}'),
('drobnikj/gpt-scraper','AI GPT Scraper','استخراج ذكي بالذكاء الاصطناعي','ai','حسب الاستهلاك','{}'::jsonb,false,true,'{ai,gpt,extraction}');
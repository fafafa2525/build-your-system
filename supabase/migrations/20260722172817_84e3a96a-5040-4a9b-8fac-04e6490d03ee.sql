
-- ========== Roles system ==========
CREATE TYPE public.app_role AS ENUM ('admin', 'user');

CREATE TABLE public.profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  display_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON public.profiles TO authenticated;
GRANT ALL ON public.profiles TO service_role;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own profile" ON public.profiles FOR SELECT TO authenticated USING (auth.uid() = id);
CREATE POLICY "Users update own profile" ON public.profiles FOR UPDATE TO authenticated USING (auth.uid() = id);

CREATE TABLE public.user_roles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role public.app_role NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, role)
);
GRANT SELECT ON public.user_roles TO authenticated;
GRANT ALL ON public.user_roles TO service_role;
ALTER TABLE public.user_roles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own roles" ON public.user_roles FOR SELECT TO authenticated USING (auth.uid() = user_id);

CREATE OR REPLACE FUNCTION public.has_role(_user_id UUID, _role public.app_role)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = public
AS $$ SELECT EXISTS (SELECT 1 FROM public.user_roles WHERE user_id = _user_id AND role = _role) $$;

-- Auto profile + first user becomes admin
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE user_count INT;
BEGIN
  INSERT INTO public.profiles (id, email, display_name)
  VALUES (NEW.id, NEW.email, COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1)));
  SELECT COUNT(*) INTO user_count FROM auth.users;
  INSERT INTO public.user_roles (user_id, role)
  VALUES (NEW.id, CASE WHEN user_count <= 1 THEN 'admin'::public.app_role ELSE 'user'::public.app_role END);
  RETURN NEW;
END; $$;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ========== updated_at helper ==========
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$;

-- ========== Apify keys ==========
CREATE TYPE public.key_status AS ENUM ('active', 'exhausted', 'disabled', 'error');

CREATE TABLE public.apify_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  label TEXT NOT NULL,
  api_key TEXT NOT NULL UNIQUE,
  status public.key_status NOT NULL DEFAULT 'active',
  usage_count INT NOT NULL DEFAULT 0,
  daily_usage INT NOT NULL DEFAULT 0,
  monthly_usage INT NOT NULL DEFAULT 0,
  daily_reset_at DATE NOT NULL DEFAULT CURRENT_DATE,
  monthly_reset_at DATE NOT NULL DEFAULT date_trunc('month', CURRENT_DATE)::date,
  last_used_at TIMESTAMPTZ,
  last_success_at TIMESTAMPTZ,
  last_error TEXT,
  last_error_at TIMESTAMPTZ,
  added_by UUID REFERENCES auth.users(id),
  added_via TEXT NOT NULL DEFAULT 'web',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_apify_keys_status ON public.apify_keys(status);
CREATE TRIGGER apify_keys_updated_at BEFORE UPDATE ON public.apify_keys
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

GRANT SELECT, INSERT, UPDATE, DELETE ON public.apify_keys TO authenticated;
GRANT ALL ON public.apify_keys TO service_role;
ALTER TABLE public.apify_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Authenticated users manage keys" ON public.apify_keys FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- ========== Searches (jobs) ==========
CREATE TYPE public.search_status AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled');

CREATE TABLE public.searches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  keyword TEXT NOT NULL,
  country TEXT NOT NULL,
  language TEXT,
  ad_type TEXT DEFAULT 'all',
  max_pages INT DEFAULT 100,
  status public.search_status NOT NULL DEFAULT 'pending',
  progress INT NOT NULL DEFAULT 0,
  progress_message TEXT,
  pages_found INT NOT NULL DEFAULT 0,
  numbers_found INT NOT NULL DEFAULT 0,
  numbers_new INT NOT NULL DEFAULT 0,
  error_message TEXT,
  apify_run_id TEXT,
  telegram_chat_id BIGINT,
  telegram_user_id BIGINT,
  source TEXT NOT NULL DEFAULT 'web',
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  duration_seconds INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_searches_status ON public.searches(status);
CREATE INDEX idx_searches_created_at ON public.searches(created_at DESC);
CREATE TRIGGER searches_updated_at BEFORE UPDATE ON public.searches
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

GRANT SELECT, INSERT, UPDATE, DELETE ON public.searches TO authenticated;
GRANT ALL ON public.searches TO service_role;
ALTER TABLE public.searches ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Authenticated read searches" ON public.searches FOR SELECT TO authenticated USING (true);
CREATE POLICY "Authenticated write searches" ON public.searches FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "Authenticated update searches" ON public.searches FOR UPDATE TO authenticated USING (true);
CREATE POLICY "Authenticated delete searches" ON public.searches FOR DELETE TO authenticated USING (true);

-- ========== Facebook pages found per search ==========
CREATE TABLE public.search_pages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  search_id UUID NOT NULL REFERENCES public.searches(id) ON DELETE CASCADE,
  page_url TEXT NOT NULL,
  page_name TEXT,
  numbers_extracted INT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_search_pages_search ON public.search_pages(search_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.search_pages TO authenticated;
GRANT ALL ON public.search_pages TO service_role;
ALTER TABLE public.search_pages ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Auth manage search_pages" ON public.search_pages FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- ========== Extracted numbers (unified) ==========
CREATE TABLE public.extracted_numbers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone TEXT NOT NULL UNIQUE,
  country TEXT,
  times_found INT NOT NULL DEFAULT 1,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  first_search_id UUID REFERENCES public.searches(id) ON DELETE SET NULL,
  last_search_id UUID REFERENCES public.searches(id) ON DELETE SET NULL,
  page_url TEXT,
  page_name TEXT,
  is_sent BOOLEAN NOT NULL DEFAULT false,
  sent_at TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_numbers_phone ON public.extracted_numbers(phone);
CREATE INDEX idx_numbers_is_sent ON public.extracted_numbers(is_sent);
CREATE INDEX idx_numbers_last_seen ON public.extracted_numbers(last_seen_at DESC);
CREATE INDEX idx_numbers_country ON public.extracted_numbers(country);
CREATE TRIGGER numbers_updated_at BEFORE UPDATE ON public.extracted_numbers
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

GRANT SELECT, INSERT, UPDATE, DELETE ON public.extracted_numbers TO authenticated;
GRANT ALL ON public.extracted_numbers TO service_role;
ALTER TABLE public.extracted_numbers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Auth manage numbers" ON public.extracted_numbers FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- Junction: which numbers came from which search (for history)
CREATE TABLE public.search_numbers (
  search_id UUID NOT NULL REFERENCES public.searches(id) ON DELETE CASCADE,
  number_id UUID NOT NULL REFERENCES public.extracted_numbers(id) ON DELETE CASCADE,
  is_new_at_time BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (search_id, number_id)
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.search_numbers TO authenticated;
GRANT ALL ON public.search_numbers TO service_role;
ALTER TABLE public.search_numbers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Auth manage search_numbers" ON public.search_numbers FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- ========== Job logs ==========
CREATE TABLE public.job_logs (
  id BIGSERIAL PRIMARY KEY,
  search_id UUID REFERENCES public.searches(id) ON DELETE CASCADE,
  level TEXT NOT NULL DEFAULT 'info',
  message TEXT NOT NULL,
  meta JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_job_logs_search ON public.job_logs(search_id, created_at DESC);
GRANT SELECT, INSERT, DELETE ON public.job_logs TO authenticated;
GRANT ALL ON public.job_logs TO service_role;
ALTER TABLE public.job_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Auth read logs" ON public.job_logs FOR SELECT TO authenticated USING (true);
CREATE POLICY "Auth insert logs" ON public.job_logs FOR INSERT TO authenticated WITH CHECK (true);
CREATE POLICY "Auth delete logs" ON public.job_logs FOR DELETE TO authenticated USING (true);

-- ========== Bot settings (single row) ==========
CREATE TABLE public.bot_settings (
  id INT PRIMARY KEY DEFAULT 1,
  allowed_telegram_ids BIGINT[] NOT NULL DEFAULT '{}',
  default_country TEXT DEFAULT 'DZ',
  default_max_pages INT DEFAULT 100,
  auto_send_results BOOLEAN NOT NULL DEFAULT true,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT single_row CHECK (id = 1)
);
INSERT INTO public.bot_settings (id) VALUES (1);
GRANT SELECT, UPDATE ON public.bot_settings TO authenticated;
GRANT ALL ON public.bot_settings TO service_role;
ALTER TABLE public.bot_settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Auth read settings" ON public.bot_settings FOR SELECT TO authenticated USING (true);
CREATE POLICY "Auth update settings" ON public.bot_settings FOR UPDATE TO authenticated USING (true);
CREATE TRIGGER bot_settings_updated_at BEFORE UPDATE ON public.bot_settings
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ========== Health status ==========
CREATE TABLE public.health_status (
  service TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'unknown',
  last_heartbeat TIMESTAMPTZ,
  details JSONB,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT ON public.health_status TO authenticated;
GRANT ALL ON public.health_status TO service_role;
ALTER TABLE public.health_status ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Auth read health" ON public.health_status FOR SELECT TO authenticated USING (true);
CREATE TRIGGER health_status_updated_at BEFORE UPDATE ON public.health_status
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

INSERT INTO public.health_status (service, status) VALUES
  ('vps', 'unknown'),
  ('telegram_bot', 'unknown'),
  ('apify', 'unknown')
ON CONFLICT DO NOTHING;

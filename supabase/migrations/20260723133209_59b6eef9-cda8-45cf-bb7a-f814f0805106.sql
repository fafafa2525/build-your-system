
-- فتح الوصول العام لجميع الجداول (بدون تسجيل دخول)
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY['apify_keys','bot_settings','extracted_numbers','health_status','job_logs','search_numbers','search_pages','searches']) LOOP
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO anon', t);
    EXECUTE format('DROP POLICY IF EXISTS "public_all" ON public.%I', t);
    EXECUTE format('CREATE POLICY "public_all" ON public.%I FOR ALL TO anon, authenticated USING (true) WITH CHECK (true)', t);
  END LOOP;
END $$;

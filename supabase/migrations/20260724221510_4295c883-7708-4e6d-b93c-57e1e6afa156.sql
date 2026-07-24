
-- 1. Contact validations table (generic engine)
CREATE TABLE public.contact_validations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_type TEXT NOT NULL,           -- 'phone' | 'email' | 'website' | 'telegram' | ...
  contact_value TEXT NOT NULL,          -- normalized value
  validator TEXT NOT NULL,              -- 'whatsapp' | 'email_smtp' | 'website_ping' | ...
  status TEXT NOT NULL DEFAULT 'pending', -- pending|running|valid|invalid|cached|error
  result JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_message TEXT,
  attempts INT NOT NULL DEFAULT 0,
  checked_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,               -- when cache is no longer valid
  source_search_id UUID REFERENCES public.searches(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT contact_validations_status_chk
    CHECK (status IN ('pending','running','valid','invalid','cached','error'))
);

CREATE UNIQUE INDEX contact_validations_unique
  ON public.contact_validations (contact_type, contact_value, validator);
CREATE INDEX idx_cv_status         ON public.contact_validations (status);
CREATE INDEX idx_cv_validator      ON public.contact_validations (validator);
CREATE INDEX idx_cv_expires        ON public.contact_validations (expires_at);
CREATE INDEX idx_cv_type_value     ON public.contact_validations (contact_type, contact_value);
CREATE INDEX idx_cv_checked        ON public.contact_validations (checked_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.contact_validations TO authenticated, anon;
GRANT ALL ON public.contact_validations TO service_role;

ALTER TABLE public.contact_validations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public_all" ON public.contact_validations
  FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);

CREATE TRIGGER cv_updated_at BEFORE UPDATE ON public.contact_validations
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- 2. Cache lookup helper: returns a valid (non-expired) validation row if present
CREATE OR REPLACE FUNCTION public.get_valid_validation(
  _contact_type TEXT,
  _contact_value TEXT,
  _validator TEXT
)
RETURNS public.contact_validations
LANGUAGE sql
STABLE
SET search_path = public
AS $$
  SELECT *
  FROM public.contact_validations
  WHERE contact_type = _contact_type
    AND contact_value = _contact_value
    AND validator = _validator
    AND status IN ('valid','invalid','cached')
    AND (expires_at IS NULL OR expires_at > now())
  ORDER BY checked_at DESC NULLS LAST
  LIMIT 1
$$;

-- 3. Convenience column for future "has website" filter
ALTER TABLE public.extracted_numbers
  ADD COLUMN IF NOT EXISTS has_website BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS website TEXT,
  ADD COLUMN IF NOT EXISTS email TEXT;

CREATE INDEX IF NOT EXISTS idx_numbers_has_website ON public.extracted_numbers (has_website);
CREATE INDEX IF NOT EXISTS idx_numbers_email       ON public.extracted_numbers (email) WHERE email IS NOT NULL;

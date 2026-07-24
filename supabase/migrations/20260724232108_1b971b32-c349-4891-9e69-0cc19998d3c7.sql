-- Providers/sources support
ALTER TABLE public.searches
  ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'facebook',
  ADD COLUMN IF NOT EXISTS city TEXT,
  ADD COLUMN IF NOT EXISTS category TEXT;

CREATE INDEX IF NOT EXISTS searches_provider_idx ON public.searches(provider);

ALTER TABLE public.extracted_numbers
  ADD COLUMN IF NOT EXISTS sources TEXT[] NOT NULL DEFAULT ARRAY['facebook']::text[],
  ADD COLUMN IF NOT EXISTS business_name TEXT,
  ADD COLUMN IF NOT EXISTS category TEXT,
  ADD COLUMN IF NOT EXISTS address TEXT,
  ADD COLUMN IF NOT EXISTS city TEXT,
  ADD COLUMN IF NOT EXISTS rating NUMERIC,
  ADD COLUMN IF NOT EXISTS reviews_count INTEGER,
  ADD COLUMN IF NOT EXISTS latitude NUMERIC,
  ADD COLUMN IF NOT EXISTS longitude NUMERIC,
  ADD COLUMN IF NOT EXISTS google_maps_url TEXT;

CREATE INDEX IF NOT EXISTS extracted_numbers_sources_idx ON public.extracted_numbers USING GIN(sources);
CREATE INDEX IF NOT EXISTS extracted_numbers_city_idx ON public.extracted_numbers(city);
CREATE INDEX IF NOT EXISTS extracted_numbers_category_idx ON public.extracted_numbers(category);

-- Backfill: existing rows are all facebook-origin
UPDATE public.extracted_numbers
   SET sources = ARRAY['facebook']::text[]
 WHERE sources IS NULL OR array_length(sources, 1) IS NULL;
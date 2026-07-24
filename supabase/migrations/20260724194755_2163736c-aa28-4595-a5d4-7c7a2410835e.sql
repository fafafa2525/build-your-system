ALTER TABLE public.extracted_numbers ADD COLUMN IF NOT EXISTS kind text;
CREATE INDEX IF NOT EXISTS idx_extracted_numbers_kind ON public.extracted_numbers(kind);
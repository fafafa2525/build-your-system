ALTER TABLE public.extracted_numbers
  ADD COLUMN IF NOT EXISTS email TEXT,
  ADD COLUMN IF NOT EXISTS claim_this_business BOOLEAN;
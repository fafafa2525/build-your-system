-- Enable pg_cron for scheduled maintenance
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Watchdog: fail searches stuck in 'running' > 30 minutes
CREATE OR REPLACE FUNCTION public.watchdog_stuck_searches()
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  UPDATE public.searches
  SET status = 'failed',
      error_message = COALESCE(error_message, 'watchdog: exceeded 30 minutes'),
      finished_at = now(),
      duration_seconds = COALESCE(duration_seconds, EXTRACT(EPOCH FROM (now() - started_at))::int)
  WHERE status = 'running'
    AND started_at IS NOT NULL
    AND started_at < now() - INTERVAL '30 minutes';
$$;

-- Unschedule if already exists (idempotent)
DO $$
BEGIN
  PERFORM cron.unschedule('adsbot-watchdog-stuck-jobs')
  WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'adsbot-watchdog-stuck-jobs');
EXCEPTION WHEN OTHERS THEN NULL;
END $$;

SELECT cron.schedule(
  'adsbot-watchdog-stuck-jobs',
  '*/10 * * * *',
  $$ SELECT public.watchdog_stuck_searches(); $$
);

-- Index to speed up per-user daily rate limit lookups
CREATE INDEX IF NOT EXISTS idx_searches_user_created
  ON public.searches (telegram_user_id, created_at DESC)
  WHERE telegram_user_id IS NOT NULL;
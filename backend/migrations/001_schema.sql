-- ============================================================
-- Matches the existing Supabase table schema exactly.
-- Only run this if the table does not already exist.
-- ============================================================

create table if not exists public.analyses (
  id             uuid        primary key default gen_random_uuid(),
  user_id        uuid        references auth.users(id) on delete cascade,
  ticker_name    text,
  prompt         text,
  advice         text,
  created_at     timestamptz not null default now(),
  approve_count  int4,
  reject_count   int4,
  council_verdict text
);

-- Indexes
create index if not exists analyses_user_id_idx    on public.analyses (user_id);
create index if not exists analyses_created_at_idx on public.analyses (created_at desc);

-- Row Level Security
alter table public.analyses enable row level security;

create policy "select own analyses"
  on public.analyses for select
  using (auth.uid() = user_id);

create policy "insert own analyses"
  on public.analyses for insert
  with check (auth.uid() = user_id);

create policy "delete own analyses"
  on public.analyses for delete
  using (auth.uid() = user_id);

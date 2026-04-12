-- ============================================================
-- Run this in: Supabase Dashboard → SQL Editor → New Query
-- ============================================================

-- Analyses table
create table if not exists public.analyses (
  id             uuid        primary key default gen_random_uuid(),
  user_id        uuid        not null references auth.users(id) on delete cascade,
  ticker         text        not null,
  intent         text        not null,
  analysis_text  text,
  council_verdict text        check (council_verdict in ('approved', 'rejected')),
  approve_count  int         not null default 0,
  reject_count   int         not null default 0,
  created_at     timestamptz not null default now()
);

-- Indexes
create index if not exists analyses_user_id_idx    on public.analyses (user_id);
create index if not exists analyses_created_at_idx on public.analyses (created_at desc);

-- Row Level Security
alter table public.analyses enable row level security;

-- Users can only see / insert / delete their own rows
create policy "select own analyses"
  on public.analyses for select
  using (auth.uid() = user_id);

create policy "insert own analyses"
  on public.analyses for insert
  with check (auth.uid() = user_id);

create policy "delete own analyses"
  on public.analyses for delete
  using (auth.uid() = user_id);

-- Migrations for a live database, in order. schema.sql is the whole schema for a fresh one.
-- teamloop_cloud_v1 is schema.sql as first applied (teams through snapshots).

-- teamloop_cloud_v2_tasks: tasks planned on the board before any session reports on them
create table if not exists public.tasks (
  team_id uuid not null references public.teams(id) on delete cascade,
  task text not null,
  title text not null check (char_length(title) between 1 and 120),
  owner_id uuid,
  owner_name text,
  state text not null default 'open' check (state in ('open', 'closed')),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (team_id, task)
);
alter table public.tasks enable row level security;

-- teamloop_cloud_v3_usage: Super Agents' own model use, for the usage counter
create table if not exists public.agent_usage (
  id bigserial primary key,
  team_id uuid not null references public.teams(id) on delete cascade,
  user_id uuid,
  member text,
  source text not null check (source in ('app', 'ask', 'agent', 'digest', 'progress')),
  model text,
  calls int not null default 0,
  tokens_in bigint not null default 0,
  tokens_out bigint not null default 0,
  at timestamptz not null default now()
);
create index if not exists agent_usage_team_at_idx on public.agent_usage (team_id, at);
alter table public.agent_usage enable row level security;

-- teamloop_cloud_v4_super_team: deadlines, and prompts into teammates' coding sessions
alter table public.tasks add column if not exists due date;
create table if not exists public.session_access (
  team_id uuid not null references public.teams(id) on delete cascade,
  user_id uuid not null,
  mode text not null default 'ask' check (mode in ('off', 'ask', 'auto')),
  access text not null default 'read' check (access in ('read', 'edit')),
  daily_tokens bigint check (daily_tokens is null or daily_tokens > 0),
  app_seen_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (team_id, user_id)
);
create table if not exists public.session_prompts (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  from_user uuid not null,
  from_name text not null,
  to_user uuid not null,
  to_name text not null,
  session text not null,
  tool text not null check (tool in ('claude_code', 'codex')),
  repo text,
  task text,
  prompt text not null check (char_length(prompt) between 1 and 4000),
  access text not null check (access in ('read', 'edit')),
  status text not null default 'pending'
    check (status in ('pending', 'approved', 'running', 'done', 'failed', 'denied', 'cancelled', 'stopped')),
  decided_by text check (decided_by in ('owner', 'auto')),
  budget bigint,
  run_session text,
  result text,
  tokens bigint not null default 0,
  created_at timestamptz not null default now(),
  decided_at timestamptz,
  finished_at timestamptz
);
create index if not exists session_prompts_team_idx on public.session_prompts (team_id, created_at desc);
alter table public.session_access enable row level security;
alter table public.session_prompts enable row level security;

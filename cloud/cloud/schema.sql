-- TeamLoop cloud hub: the whole schema for a fresh database. A live one gets migrations.sql, in order.
-- Every table has RLS on and no policies: nothing is reachable through PostgREST (anon/authenticated);
-- only the hub's server-side connection reads and writes.

create table public.teams (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 1 and 80),
  created_by uuid not null,
  created_at timestamptz not null default now()
);

create table public.memberships (
  team_id uuid not null references public.teams(id) on delete cascade,
  user_id uuid not null,
  email text,
  name text not null,
  role text not null check (role in ('lead', 'member')),
  created_at timestamptz not null default now(),
  removed_at timestamptz,
  primary key (team_id, user_id)
);
create index memberships_user_idx on public.memberships (user_id);

create table public.invites (
  token_hash text primary key,
  team_id uuid not null references public.teams(id) on delete cascade,
  role text not null default 'member' check (role in ('lead', 'member')),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  max_uses int not null default 20,
  uses int not null default 0,
  revoked boolean not null default false
);
create index invites_team_idx on public.invites (team_id);

create table public.hub_sessions (
  token_hash text primary key,
  user_id uuid not null,
  email text,
  name text,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index hub_sessions_user_idx on public.hub_sessions (user_id);

-- `teamloop login`: the CLI starts a device code, the person approves it on the web, the CLI claims a token once.
create table public.devices (
  device_hash text primary key,
  user_code text not null unique,
  status text not null default 'pending' check (status in ('pending', 'approved', 'claimed', 'denied')),
  user_id uuid,
  team_id uuid references public.teams(id) on delete cascade,
  token text,  -- the connector token in plain text, only until the CLI claims it (minutes)
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);

create table public.connector_tokens (
  token_hash text primary key,
  user_id uuid not null,
  team_id uuid not null references public.teams(id) on delete cascade,
  label text,
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  revoked boolean not null default false
);
create index connector_tokens_team_idx on public.connector_tokens (team_id, user_id);

create table public.events (
  team_id uuid not null references public.teams(id) on delete cascade,
  id text not null,
  user_id uuid,
  member text not null,
  task text,
  kind text not null,
  ts text not null,
  body jsonb not null,
  received_at timestamptz not null default now(),
  primary key (team_id, id)
);
create index events_team_task_ts_idx on public.events (team_id, task, ts);
create index events_team_received_idx on public.events (team_id, received_at);

create table public.snapshots (
  id bigserial primary key,
  team_id uuid not null references public.teams(id) on delete cascade,
  task text not null,
  created_at timestamptz not null default now(),
  body jsonb not null
);
create index snapshots_team_task_idx on public.snapshots (team_id, task, created_at desc);

-- v2 (migration teamloop_cloud_v2_tasks): tasks planned on the board, by people or by Agent S, before any session
-- reports on them. A task with session events shows its live progress; a planned one shows "to do" until then.
create table public.tasks (
  team_id uuid not null references public.teams(id) on delete cascade,
  task text not null,
  title text not null check (char_length(title) between 1 and 120),
  owner_id uuid,
  owner_name text,
  state text not null default 'open' check (state in ('open', 'closed')),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  due date,  -- v4
  primary key (team_id, task)
);

-- v3 (migration teamloop_cloud_v3_usage): Super Agents' own model use, for the usage counter: the app's agent steps
-- (/v1/llm), Agent S's answers, plans, progress and digests. Coding agents' tokens ride on their turn events instead.
-- user_id is null for work Agent S does for the whole team (progress, digest).
create table public.agent_usage (
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
create index agent_usage_team_at_idx on public.agent_usage (team_id, at);

-- v4 (migration teamloop_cloud_v4_super_team): Super Team. A teammate or the lead sends a prompt into someone's coding
-- session; the owner's rules (off, ask each time, automatic; read-only or edit; tokens per teammate per day) decide,
-- the owner's Super Agents runs it as a fork of that session, and every prompt stays on record. Plus task deadlines.
create table public.session_access (
  team_id uuid not null references public.teams(id) on delete cascade,
  user_id uuid not null,
  mode text not null default 'ask' check (mode in ('off', 'ask', 'auto')),
  access text not null default 'read' check (access in ('read', 'edit')),
  daily_tokens bigint check (daily_tokens is null or daily_tokens > 0),
  app_seen_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (team_id, user_id)
);
create table public.session_prompts (
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
create index session_prompts_team_idx on public.session_prompts (team_id, created_at desc);

alter table public.teams enable row level security;
alter table public.session_access enable row level security;
alter table public.session_prompts enable row level security;
alter table public.agent_usage enable row level security;
alter table public.tasks enable row level security;
alter table public.memberships enable row level security;
alter table public.invites enable row level security;
alter table public.hub_sessions enable row level security;
alter table public.devices enable row level security;
alter table public.connector_tokens enable row level security;
alter table public.events enable row level security;
alter table public.snapshots enable row level security;

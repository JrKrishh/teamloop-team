-- TeamLoop cloud hub, v1 (applied to Supabase project `teamloop` as migration teamloop_cloud_v1).
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

alter table public.teams enable row level security;
alter table public.memberships enable row level security;
alter table public.invites enable row level security;
alter table public.hub_sessions enable row level security;
alter table public.devices enable row level security;
alter table public.connector_tokens enable row level security;
alter table public.events enable row level security;
alter table public.snapshots enable row level security;

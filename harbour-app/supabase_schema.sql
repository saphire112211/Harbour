-- Harbour Supabase schema.
-- Run this in the Supabase SQL editor before `python seed_supabase.py`.

create table if not exists public.resources (
  resource_id text primary key,
  name text not null,
  service_type text not null,
  address text not null default '',
  hours text not null default '',
  phone text not null default '',
  email text not null default '',
  url text not null default '',
  zip_zone integer not null default 0,
  capacity integer not null default 0 check (capacity >= 0),
  max_income integer not null default 0 check (max_income >= 0),
  min_household_size integer not null default 0 check (min_household_size >= 0),
  last_verified_days_ago integer not null default 0 check (last_verified_days_ago >= 0),
  lat double precision,
  lon double precision
);

create table if not exists public.cases (
  tracking text primary key,
  plan jsonb not null default '[]'::jsonb,
  email text not null default '',
  organization_consent boolean not null default false,
  saved_at timestamptz not null default now()
);

create table if not exists public.escalations (
  id text primary key,
  user_hash text not null,
  reason text not null,
  summary text not null default '',
  urgency text not null default 'this_week',
  has_children boolean not null default false,
  safety_flag boolean not null default false,
  language text not null default 'English',
  status text not null default 'open',
  referred_to text not null default '',
  flagged_at timestamptz not null default now(),
  resolved_at timestamptz
);

-- Harbour uses a server-side Supabase key. Keep row-level access disabled unless
-- you add explicit service-role policies and real user authentication.

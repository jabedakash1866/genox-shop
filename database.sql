-- ==========================================
-- GENOX SHOP DATABASE
-- ==========================================

create extension if not exists pgcrypto;

-- ==========================================
-- 1. PROFILES TABLE
-- ==========================================

create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    email text,
    display_name text,
    avatar_url text,
    wallet_balance numeric(12,2) not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Existing profiles table থাকলে প্রয়োজনীয় column যোগ করবে

alter table public.profiles
add column if not exists email text;

alter table public.profiles
add column if not exists display_name text;

alter table public.profiles
add column if not exists avatar_url text;

alter table public.profiles
add column if not exists wallet_balance numeric(12,2) not null default 0;

alter table public.profiles
add column if not exists created_at timestamptz not null default now();

alter table public.profiles
add column if not exists updated_at timestamptz not null default now();


-- ==========================================
-- 2. ORDERS TABLE
-- ==========================================

create table if not exists public.orders (
    id uuid primary key default gen_random_uuid(),
    order_code text unique,
    user_id uuid references auth.users(id) on delete set null,
    status text not null default 'Pending',
    service text,
    category text,
    package_label text,
    duration_days integer,
    quantity integer,
    price numeric(12,2) not null default 0,
    payment_method text,
    transaction_id text,
    customer_data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

-- Existing orders table থাকলে প্রয়োজনীয় column যোগ করবে

alter table public.orders
add column if not exists order_code text;

alter table public.orders
add column if not exists user_id uuid references auth.users(id) on delete set null;

alter table public.orders
add column if not exists status text not null default 'Pending';

alter table public.orders
add column if not exists service text;

alter table public.orders
add column if not exists category text;

alter table public.orders
add column if not exists package_label text;

alter table public.orders
add column if not exists duration_days integer;

alter table public.orders
add column if not exists quantity integer;

alter table public.orders
add column if not exists price numeric(12,2) not null default 0;

alter table public.orders
add column if not exists payment_method text;

alter table public.orders
add column if not exists transaction_id text;

alter table public.orders
add column if not exists customer_data jsonb not null default '{}'::jsonb;

alter table public.orders
add column if not exists created_at timestamptz not null default now();


-- ==========================================
-- 3. UNIQUE ORDER CODE
-- ==========================================

create unique index if not exists orders_order_code_unique
on public.orders(order_code)
where order_code is not null;


-- ==========================================
-- 4. INDEXES
-- ==========================================

create index if not exists orders_user_id_idx
on public.orders(user_id);

create index if not exists orders_created_at_idx
on public.orders(created_at desc);


-- ==========================================
-- 5. ENABLE ROW LEVEL SECURITY
-- ==========================================

alter table public.profiles enable row level security;
alter table public.orders enable row level security;


-- ==========================================
-- 6. PROFILES POLICIES
-- ==========================================

drop policy if exists "Users can view own profile"
on public.profiles;

create policy "Users can view own profile"
on public.profiles
for select
to authenticated
using (auth.uid() = id);


drop policy if exists "Users can insert own profile"
on public.profiles;

create policy "Users can insert own profile"
on public.profiles
for insert
to authenticated
with check (auth.uid() = id);


drop policy if exists "Users can update own profile"
on public.profiles;

create policy "Users can update own profile"
on public.profiles
for update
to authenticated
using (auth.uid() = id)
with check (auth.uid() = id);


-- ==========================================
-- 7. ORDERS POLICIES
-- ==========================================

drop policy if exists "Users can view own orders"
on public.orders;

create policy "Users can view own orders"
on public.orders
for select
to authenticated
using (auth.uid() = user_id);


drop policy if exists "Users can create own orders"
on public.orders;

create policy "Users can create own orders"
on public.orders
for insert
to authenticated
with check (auth.uid() = user_id);


-- ==========================================
-- 8. PROFILE AUTO-CREATION
-- ==========================================

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.profiles (
        id,
        email,
        display_name,
        avatar_url
    )
    values (
        new.id,
        new.email,
        coalesce(new.raw_user_meta_data ->> 'full_name',
                 new.raw_user_meta_data ->> 'name'),
        new.raw_user_meta_data ->> 'avatar_url'
    )
    on conflict (id) do update
    set
        email = excluded.email,
        updated_at = now();

    return new;
end;
$$;


drop trigger if exists on_auth_user_created
on auth.users;

create trigger on_auth_user_created
after insert on auth.users
for each row
execute procedure public.handle_new_user();


-- ==========================================
-- 9. UPDATED AT FUNCTION
-- ==========================================

create or replace function public.update_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;


drop trigger if exists profiles_updated_at
on public.profiles;

create trigger profiles_updated_at
before update on public.profiles
for each row
execute procedure public.update_updated_at();


-- ==========================================
-- GENOX SHOP DATABASE SETUP COMPLETE
-- ==========================================

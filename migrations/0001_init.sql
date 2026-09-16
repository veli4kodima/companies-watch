create table companies (
    company_number  text primary key,
    company_name    text not null,
    company_status  text,
    etag            text,
    raw             jsonb not null,
    first_seen_at   timestamptz not null default now(),
    fetched_at      timestamptz not null
);
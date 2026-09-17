create table watchlist (
                           company_number  text primary key,
                           added_at        timestamptz not null default now(),
                           next_check_at   timestamptz not null default now(),
                           last_checked_at timestamptz,
                           fail_count      integer     not null default 0,
                           paused_at       timestamptz,
                           pause_reason    text,

                           constraint watchlist_fail_count_non_negative check (fail_count >= 0),
                           constraint watchlist_pause_reason_requires_pause
                               check ((paused_at is null) = (pause_reason is null))
);

create index watchlist_due_idx
    on watchlist (next_check_at)
    where paused_at is null;
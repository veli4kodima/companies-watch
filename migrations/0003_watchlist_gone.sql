alter table watchlist
    add column gone_at timestamptz;

alter table watchlist
    add constraint watchlist_not_paused_and_gone
        check (paused_at is null or gone_at is null);

drop index watchlist_due_idx;

create index watchlist_due_idx
    on watchlist (next_check_at)
    where paused_at is null and gone_at is null;
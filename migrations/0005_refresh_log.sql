-- 0005: журнал прогонов. Одна строка = один запуск `run`.
-- "Упал" определяется по протухшему heartbeat_at; такие строки
-- следующий прогон переводит в 'abandoned'.

create table refresh_log (
                             id              bigint generated always as identity primary key,

                             started_at      timestamptz not null default now(),
                             heartbeat_at    timestamptz not null default now(),
                             finished_at     timestamptz,

                             status          text not null default 'running',

                             taken_count     int not null default 0,
                             ok_count        int not null default 0,
                             failed_count    int not null default 0,
                             gone_count      int not null default 0,
                             changed_count   int not null default 0,
                             retry_count     int not null default 0,

                             error_message   text,

                             constraint refresh_log_status_valid
                                 check (status in ('running', 'completed', 'error', 'abandoned')),

                             constraint refresh_log_status_matches_finished
                                 check ((status = 'running') = (finished_at is null)),

                             constraint refresh_log_times_ordered
                                 check (
                                     heartbeat_at >= started_at
                                         and (finished_at is null or finished_at >= started_at)
                                     ),

                             constraint refresh_log_counters_nonnegative
                                 check (
                                     taken_count >= 0 and ok_count >= 0 and failed_count >= 0
                                         and gone_count >= 0 and changed_count >= 0 and retry_count >= 0
                                     ),

                             constraint refresh_log_outcomes_within_taken
                                 check (ok_count + failed_count + gone_count <= taken_count),

                             constraint refresh_log_changed_within_ok
                                 check (changed_count <= ok_count),

                             constraint refresh_log_error_has_message
                                 check (status <> 'error' or error_message is not null)
);

-- для status: "последний прогон"
create index refresh_log_started_at_idx on refresh_log (started_at);

-- для поиска протухших: маленький, в нём только незавершённые
create index refresh_log_running_idx on refresh_log (heartbeat_at)
    where status = 'running';
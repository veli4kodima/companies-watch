create table company_changes (
                                 id              bigint generated always as identity primary key,
                                 company_number  text        not null references companies (company_number),
                                 field           text        not null,
                                 old_value       jsonb,
                                 new_value       jsonb,
                                 detected_at     timestamptz not null default now()
);

create index company_changes_company_idx
    on company_changes (company_number, detected_at desc);

create index company_changes_field_idx
    on company_changes (field, detected_at desc);
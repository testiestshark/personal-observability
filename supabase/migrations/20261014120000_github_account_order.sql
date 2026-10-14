-- Home page GitHub card: show the counts-only account first and the itemised
-- ('full') account second, so the account with a drill-down sits below the
-- plain summary. Ordering is by detail rather than by login so the migration
-- names no account.
update public.github_accounts
set display_order = case detail when 'counts_only' then 0 else 1 end;

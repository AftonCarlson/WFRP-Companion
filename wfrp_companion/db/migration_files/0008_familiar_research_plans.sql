create table if not exists familiar_research_plans (
  id text primary key,
  research_run_id text not null references familiar_research_runs(id) on delete cascade,
  revision integer not null,
  status text not null,
  intent text not null,
  plan_summary text not null,
  subject_json text not null default '{}',
  requirements_json text not null default '[]',
  planned_actions_json text not null default '[]',
  provider_call_id text,
  validation_errors_json text not null default '[]',
  created_at text not null,
  updated_at text not null,
  check(revision >= 1),
  check(status in ('proposed', 'accepted', 'rejected', 'superseded')),
  check(length(intent) > 0),
  check(length(plan_summary) > 0)
);

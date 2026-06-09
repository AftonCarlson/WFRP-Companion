create table if not exists chat_thread_context (
  thread_id text primary key references chat_threads(id) on delete cascade,
  active_subject text,
  active_intent text,
  active_book_id text references books(id) on delete set null,
  active_printed_page_label text,
  active_pdf_page_number integer,
  active_source_object_id text references source_objects(id) on delete set null,
  updated_from_message_id text references chat_messages(id) on delete set null,
  updated_from_model_run_id text references model_runs(id) on delete set null,
  metadata_json text not null default '{}',
  updated_at text not null,
  check(active_pdf_page_number is null or active_pdf_page_number >= 1)
);

create table if not exists familiar_research_runs (
  id text primary key,
  model_run_id text not null unique references model_runs(id) on delete cascade,
  thread_id text not null references chat_threads(id) on delete cascade,
  user_message_id text not null references chat_messages(id) on delete cascade,
  source_set_id text references source_sets(id) on delete set null,
  raw_query text not null,
  resolved_query text not null,
  intent text not null,
  status text not null,
  max_tool_rounds integer not null,
  tool_rounds_used integer not null default 0,
  evidence_status text not null,
  final_retrieval_run_id text references retrieval_runs(id) on delete set null,
  metadata_json text not null default '{}',
  created_at text not null,
  updated_at text not null,
  completed_at text,
  check(status in (
    'planning',
    'tool_calling',
    'validating',
    'finalizing',
    'completed',
    'insufficient',
    'failed'
  )),
  check(evidence_status in (
    'not_evaluated',
    'sufficient',
    'partial',
    'insufficient'
  )),
  check(max_tool_rounds > 0),
  check(tool_rounds_used >= 0),
  check(tool_rounds_used <= max_tool_rounds)
);

create table if not exists familiar_tool_calls (
  id text primary key,
  research_run_id text not null references familiar_research_runs(id) on delete cascade,
  step_number integer not null,
  call_index integer not null default 0,
  provider_call_id text,
  tool_name text not null,
  arguments_json text not null,
  argument_hash text not null,
  status text not null,
  retrieval_run_id text references retrieval_runs(id) on delete set null,
  output_summary_json text not null default '{}',
  error_code text,
  error_message text,
  created_at text not null,
  updated_at text not null,
  completed_at text,
  check(status in ('requested', 'running', 'succeeded', 'failed', 'rejected')),
  check(step_number >= 1),
  check(call_index >= 0),
  check(length(tool_name) > 0),
  check(length(argument_hash) > 0)
);

create table if not exists familiar_evidence_judgments (
  id text primary key,
  research_run_id text not null references familiar_research_runs(id) on delete cascade,
  retrieval_run_id text references retrieval_runs(id) on delete set null,
  retrieval_hit_id text references retrieval_hits(id) on delete set null,
  source_object_id text references source_objects(id) on delete set null,
  book_id text references books(id) on delete set null,
  printed_page_label text,
  requirement_type text not null,
  status text not null,
  reason_code text not null,
  reasons_json text not null default '[]',
  created_at text not null,
  check(status in ('accepted', 'rejected', 'partial')),
  check(length(requirement_type) > 0),
  check(length(reason_code) > 0)
);

create index if not exists ix_familiar_research_runs_model_run
on familiar_research_runs(model_run_id);

create index if not exists ix_familiar_research_runs_thread
on familiar_research_runs(thread_id, created_at);

create index if not exists ix_familiar_tool_calls_run
on familiar_tool_calls(research_run_id, step_number);

create unique index if not exists ux_familiar_tool_calls_step_call
on familiar_tool_calls(research_run_id, step_number, call_index);

create unique index if not exists ux_familiar_tool_calls_provider_call
on familiar_tool_calls(research_run_id, provider_call_id)
where provider_call_id is not null;

create index if not exists ix_familiar_tool_calls_retrieval
on familiar_tool_calls(retrieval_run_id);

create index if not exists ix_familiar_evidence_judgments_run
on familiar_evidence_judgments(research_run_id, status);

create index if not exists ix_familiar_evidence_judgments_hit
on familiar_evidence_judgments(retrieval_hit_id);

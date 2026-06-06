create table if not exists book_page_label_calibrations (
  book_id text primary key references books(id) on delete cascade,
  status text not null,
  method text not null,
  calibration_json text not null default '{}',
  page_text_snapshot_sha256 text not null,
  last_error text,
  reviewed_at text,
  updated_at text not null,
  check(status in ('not_started', 'calibrating', 'calibrated', 'needs_review', 'failed')),
  check(length(method) > 0)
);

create index if not exists ix_book_page_label_calibrations_status
on book_page_label_calibrations(status, updated_at);

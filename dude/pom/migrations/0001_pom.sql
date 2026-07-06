-- DUDE POM subsystem — Postgres migration 0001 (build instruction §1–§12).
-- The Phase-1 runtime uses the append-only JSONL store behind the same
-- contracts; this DDL is the Postgres adapter's target schema. The
-- append-only property is enforced with BEFORE UPDATE/DELETE triggers:
-- corrections supersede, nothing is overwritten.
--
-- BoundState AI 2026 — BoundState Proprietary

create table pom_source_artifacts (
  id             text primary key,
  user_id        text not null,
  title          text not null,
  source_type    text not null default 'markdown',
  content        text not null,
  content_sha256 text not null,
  created_at     timestamptz not null default now(),
  supersedes_id  text references pom_source_artifacts(id),
  metadata       jsonb not null default '{}'
);

create table pom_items (
  id                 text primary key,
  user_id            text not null,
  source_artifact_id text not null references pom_source_artifacts(id),
  source_section     text not null default '',
  source_excerpt     text not null check (length(trim(source_excerpt)) > 0),
  category           text not null check (category in (
    'identity','communication_preference','trigger_pattern',
    'reasoning_pattern','protective_factor','grounding_coordinate',
    'relationship_context','life_priority','strategic_context',
    'boundary_pattern','decision_preference','working_model',
    'historical_case_context')),
  statement          text not null,
  epistemic_status   text not null check (epistemic_status in (
    'user_stated_fact','user_reported_event','user_confirmed_pattern',
    'assistant_interpretation','working_hypothesis','derived_summary')),
  confidence_band    text not null default 'unresolved' check (confidence_band in (
    'supported','plausible','weakly_supported','unresolved','contradicted')),
  sensitivity        text not null default 'normal',
  temporal           text not null default 'durable'
                     check (temporal in ('durable','windowed','historical')),
  valid_from         timestamptz,
  valid_to           timestamptz,
  allowed_uses       jsonb not null default '[]',
  case_ref           text,
  user_confirmed     boolean not null default false,
  active             boolean not null default true,
  created_at         timestamptz not null default now(),
  supersedes_id      text references pom_items(id),
  metadata           jsonb not null default '{}',
  -- §3/§13: an unconfirmed-class status can never be user-confirmed.
  constraint interpretation_is_never_fact check (
    not (user_confirmed and epistemic_status in
      ('assistant_interpretation','working_hypothesis','derived_summary'))
  )
);

create table pom_working_models (
  id               text primary key,
  user_id          text not null,
  name             text not null,
  description      text not null,
  historical_basis jsonb not null default '[]',
  adaptive_when    text,
  components       jsonb not null default '[]',
  confidence_band  text not null default 'unresolved',
  user_confirmed   boolean not null default false,
  active           boolean not null default true,
  created_at       timestamptz not null default now(),
  supersedes_id    text references pom_working_models(id)
);

create table pom_grounding_coordinates (
  id                  text primary key,
  user_id             text not null,
  phrase              text not null,
  meaning             text not null,
  activation_contexts jsonb not null default '[]',
  contraindications   jsonb not null default '[]',
  user_confirmed      boolean not null default false,
  active              boolean not null default true,
  created_at          timestamptz not null default now(),
  supersedes_id       text references pom_grounding_coordinates(id)
);

-- §12: why did you bring this personal fact into this analysis?
create table pom_retrievals (
  id               text primary key,
  case_id          text not null,
  pom_item_id      text not null references pom_items(id),
  analysis_run_id  text not null,
  retrieval_reason text not null,
  allowed_use      text not null check (allowed_use in (
    'communication_adaptation','trigger_context','uncertainty_widening',
    'grounding','safety_context','action_constraint','strategic_context',
    'relationship_context','case_retrieval')),
  retrieved_at     timestamptz not null default now()
);

create index pom_items_user_idx on pom_items (user_id, active);
create index pom_retrievals_case_idx on pom_retrievals (case_id);

-- Append-only enforcement: supersede, never mutate.
create or replace function pom_immutable() returns trigger as $$
begin
  raise exception 'POM records are append-only; supersede instead (§1/§16)';
end $$ language plpgsql;

create trigger pom_source_artifacts_ro before update or delete
  on pom_source_artifacts for each row execute function pom_immutable();
create trigger pom_items_ro before update or delete
  on pom_items for each row execute function pom_immutable();
create trigger pom_working_models_ro before update or delete
  on pom_working_models for each row execute function pom_immutable();
create trigger pom_grounding_ro before update or delete
  on pom_grounding_coordinates for each row execute function pom_immutable();
create trigger pom_retrievals_ro before update or delete
  on pom_retrievals for each row execute function pom_immutable();

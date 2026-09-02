-- Migration 016: Wiki layer
-- Persistent markdown wiki pages maintained by LLM agents.
-- Implements the "compiled knowledge base" pattern: agents accumulate structured
-- knowledge across sessions rather than re-deriving at query time.

CREATE TABLE IF NOT EXISTS wiki_page (
  page_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain              TEXT NOT NULL,
  slug                TEXT NOT NULL,
  title               TEXT NOT NULL,
  content             TEXT NOT NULL DEFAULT '',
  page_type           TEXT NOT NULL
    CHECK (page_type IN (
      'entity',          -- single artefact or named object page
      'concept',         -- domain concept (glaze type, kiln, period, …)
      'source_summary',  -- condensed summary of one ingested document
      'comparison',      -- multi-object analysis or comparison result
      'index',           -- auto-managed directory page
      'log'              -- append-only time log (one row per entry)
    )),
  knowledge_level     TEXT
    CHECK (knowledge_level IN (
      'fact_like',
      'topic_like',
      'concept_like',
      'generalization_like',
      'principle_like',
      'theory_like'
    )),
  authority_kind      TEXT
    CHECK (authority_kind IN (
      'accepted_ontology',
      'compiled_summary',
      'methodology',
      'candidate_derived'
    )),
  tags                JSONB NOT NULL DEFAULT '[]',
  source_count        INT NOT NULL DEFAULT 0,
  confidence          DOUBLE PRECISION NOT NULL DEFAULT 0.5
    CHECK (confidence BETWEEN 0 AND 1),
  last_reinforced_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  superseded_by       UUID REFERENCES wiki_page(page_id),
  UNIQUE(domain, slug)
);

-- Internal page links (wiki graph)
CREATE TABLE IF NOT EXISTS wiki_page_link (
  from_page_id  UUID NOT NULL REFERENCES wiki_page(page_id) ON DELETE CASCADE,
  to_page_id    UUID NOT NULL REFERENCES wiki_page(page_id) ON DELETE CASCADE,
  link_text     TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (from_page_id, to_page_id)
);

-- Structured operation log for audit and analytics
CREATE TABLE IF NOT EXISTS wiki_operation_log (
  log_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain        TEXT NOT NULL,
  action_type   TEXT NOT NULL
    CHECK (action_type IN ('ingest', 'query', 'lint', 'crystallize', 'export')),
  source_ref    TEXT,
  pages_touched INT NOT NULL DEFAULT 0,
  summary       TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_wiki_page_domain_type
  ON wiki_page (domain, page_type);

CREATE INDEX IF NOT EXISTS idx_wiki_page_domain_reinforced
  ON wiki_page (domain, last_reinforced_at DESC);

CREATE INDEX IF NOT EXISTS idx_wiki_page_domain_updated
  ON wiki_page (domain, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_wiki_page_link_to_page
  ON wiki_page_link (to_page_id);

CREATE INDEX IF NOT EXISTS idx_wiki_operation_log_domain_created
  ON wiki_operation_log (domain, created_at DESC);

-- Full-text search index on title + content
CREATE INDEX IF NOT EXISTS idx_wiki_page_tsv
  ON wiki_page USING GIN (
  to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))
);

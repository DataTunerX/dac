-- Migration 017: Wiki supersession
--
-- Replace the global UNIQUE(domain, slug) constraint with a partial unique index
-- that only enforces uniqueness on *current* pages (superseded_by IS NULL).
-- This lets old versions share the same slug after a supersession event.
--
-- Behaviour after migration:
--   upsert without supersede → ON CONFLICT (domain, slug) WHERE superseded_by IS NULL DO UPDATE
--   upsert with supersede=true → INSERT new row, UPDATE old row SET superseded_by = new_page_id
--   GET/search queries already filter WHERE superseded_by IS NULL (current pages only)

ALTER TABLE wiki_page DROP CONSTRAINT IF EXISTS wiki_page_domain_slug_key;

CREATE UNIQUE INDEX IF NOT EXISTS wiki_page_current_slug_idx
  ON wiki_page(domain, slug)
  WHERE superseded_by IS NULL;

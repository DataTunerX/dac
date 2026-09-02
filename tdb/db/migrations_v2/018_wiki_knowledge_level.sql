ALTER TABLE wiki_page
  ADD COLUMN IF NOT EXISTS knowledge_level TEXT
    CHECK (knowledge_level IN (
      'fact_like',
      'topic_like',
      'concept_like',
      'generalization_like',
      'principle_like',
      'theory_like'
    )),
  ADD COLUMN IF NOT EXISTS authority_kind TEXT
    CHECK (authority_kind IN (
      'accepted_ontology',
      'compiled_summary',
      'methodology',
      'candidate_derived'
    ));

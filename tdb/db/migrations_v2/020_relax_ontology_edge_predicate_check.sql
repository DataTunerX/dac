-- Relax ontology_edge predicate validation for domain-profile relation promotion.
--
-- Domain profiles seed their allowed relation predicates into
-- ontology_relation_type. ontology_edge should enforce a sane predicate shape,
-- not a small hard-coded list that breaks new domains such as enterprise
-- storage.
--
-- ontology_edge lives in the ontology extension (002_v2_ontology_extension.sql),
-- which the `core` migration profile skips. Guard on to_regclass so this file is
-- a no-op when the ontology layer is not installed, instead of erroring on
-- 'ontology_edge'::regclass.

DO $$
DECLARE rec RECORD;
BEGIN
  IF to_regclass('ontology_edge') IS NULL THEN
    RAISE NOTICE 'ontology_edge not present (core profile); skipping predicate-check relaxation';
    RETURN;
  END IF;

  FOR rec IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'ontology_edge'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%predicate%'
  LOOP
    EXECUTE format('ALTER TABLE ontology_edge DROP CONSTRAINT IF EXISTS %I', rec.conname);
  END LOOP;

  BEGIN
    ALTER TABLE ontology_edge
      ADD CONSTRAINT ck_ontology_edge_predicate
      CHECK (predicate ~ '^[a-z][a-z0-9_]*$');
  EXCEPTION
    WHEN duplicate_object THEN
      NULL;
  END;
END $$;

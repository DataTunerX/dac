-- Keep ontology_edge predicate validation replay-safe for extended domain
-- relation promotion.
--
-- ontology_edge lives in the ontology extension (002_v2_ontology_extension.sql),
-- which the `core` migration profile skips. Guard on to_regclass so this file is
-- a no-op when the ontology layer is not installed, instead of erroring on
-- 'ontology_edge'::regclass.

DO $$
DECLARE rec RECORD;
BEGIN
  IF to_regclass('ontology_edge') IS NULL THEN
    RAISE NOTICE 'ontology_edge not present (core profile); skipping ceramics predicate extension';
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

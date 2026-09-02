-- Repair ontology_edge predicate validation on long-lived databases.
--
-- Some existing databases were left in a half-upgraded state because older
-- migration replays attempted to re-apply a hard-coded predicate enum after
-- domain-specific predicates had already been written. The runtime invariant we
-- want is the same as 020_relax_ontology_edge_predicate_check.sql: predicate
-- must be snake_case, not pre-registered in a tiny fixed list.

DO $$
DECLARE rec RECORD;
BEGIN
  IF to_regclass('ontology_edge') IS NULL THEN
    RAISE NOTICE 'ontology_edge not present (core profile); skipping predicate constraint repair';
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

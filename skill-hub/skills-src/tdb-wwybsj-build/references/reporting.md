# Reporting

When reporting a build, rebuild, or new-artifact intake to the user, include only
facts verified by gateway readback or explicit script output.

## Include

- What artifact or artifact set was processed.
- Which layers ran: ingest, L0, L1, L2, stance, L3, wiki.
- What was written: statement counts, wiki slug, evidence gaps, and reused
  remote concepts when available.
- Coverage quality: strong, partial, thin, none, or the concrete failure state.
- Verification commands and their observed results.

## Avoid

- Do not say "confirmed" when the system only retrieved related text.
- Do not imply the remote corpus has no evidence when a suspect timeout occurred.
- Do not report planned writes as completed writes.
- Do not hide skipped layers behind `--build`; name exactly where the pipeline
  stopped.

## Useful Commands

```bash
python3 wwybsj_verify.py
python3 wwybsj_predicates.py --validate
python3 wwybsj_l2_report.py
python3 wwybsj_wiki.py --registry-no <登记号> --verify-determinism
```

If any command cannot be run, say so and give the exact reason.

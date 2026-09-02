# DB Queries

All SQL used by services must live in this folder.

Rules:
- Use Slonik `sql` tagged templates only.
- Do not construct raw SQL strings in routes/services.
- Keep bitemporal filters centralized in shared query helpers.

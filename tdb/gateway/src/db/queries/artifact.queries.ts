import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';
import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export type ArtifactRow = {
  artifact_id: string;
  artifact_type: string;
  name: string;
  description: string | null;
  created_at: string;
};

export async function insertArtifact(
  db: Queryable,
  input: { artifactType: string; name: string; description?: string }
): Promise<ArtifactRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO artifact (
      artifact_type,
      name,
      description
    ) VALUES (
      ${input.artifactType},
      ${input.name},
      ${input.description ?? null}
    )
    RETURNING
      artifact_id::text,
      artifact_type,
      name,
      description,
      created_at::text
  `);
  return row as unknown as ArtifactRow;
}

export type ArtifactVersionRow = {
  artifact_version_id: string;
  artifact_id: string;
  version_number: number;
  status: string;
  valid_from: string;
  valid_to: string | null;
  system_from: string;
  system_to: string | null;
  content_ref: string;
  content_hash: string | null;
  author_id: string | null;
  approver_id: string | null;
  created_at: string;
};

export async function insertArtifactVersion(
  db: Queryable,
  input: {
    artifactId: string;
    versionNumber: number;
    status: string;
    validFrom: string;
    validTo?: string;
    systemFrom?: string;
    contentRef: string;
    contentHash?: string;
    authorId?: string;
    approverId?: string;
  }
): Promise<ArtifactVersionRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO artifact_version (
      artifact_id,
      version_number,
      status,
      valid_from,
      valid_to,
      system_from,
      content_ref,
      content_hash,
      author_id,
      approver_id
    ) VALUES (
      ${input.artifactId}::uuid,
      ${input.versionNumber},
      ${input.status},
      ${input.validFrom}::timestamptz,
      ${input.validTo ?? null}::timestamptz,
      COALESCE(${input.systemFrom ?? null}::timestamptz, NOW()),
      ${input.contentRef},
      ${input.contentHash ?? null},
      ${input.authorId ?? null}::uuid,
      ${input.approverId ?? null}::uuid
    )
    RETURNING
      artifact_version_id::text,
      artifact_id::text,
      version_number,
      status,
      valid_from::text,
      valid_to::text,
      system_from::text,
      system_to::text,
      content_ref,
      content_hash,
      author_id::text,
      approver_id::text,
      created_at::text
  `);

  return row as unknown as ArtifactVersionRow;
}

export async function findArtifactVersionAsOf(
  db: Queryable,
  input: { artifactId: string; asOfValidTime: string }
): Promise<ArtifactVersionRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      artifact_version_id::text,
      artifact_id::text,
      version_number,
      status,
      valid_from::text,
      valid_to::text,
      system_from::text,
      system_to::text,
      content_ref,
      content_hash,
      author_id::text,
      approver_id::text,
      created_at::text
    FROM artifact_version
    WHERE artifact_id = ${input.artifactId}::uuid
      AND valid_from <= ${input.asOfValidTime}::timestamptz
      AND (valid_to IS NULL OR valid_to > ${input.asOfValidTime}::timestamptz)
      AND system_from <= NOW()
      AND (system_to IS NULL OR system_to > NOW())
    ORDER BY valid_from DESC, version_number DESC, created_at DESC
    LIMIT 1
  `);

  return row ? (row as unknown as ArtifactVersionRow) : undefined;
}

export async function findArtifactVersionById(
  db: Queryable,
  artifactVersionId: string
): Promise<ArtifactVersionRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      artifact_version_id::text,
      artifact_id::text,
      version_number,
      status,
      valid_from::text,
      valid_to::text,
      system_from::text,
      system_to::text,
      content_ref,
      content_hash,
      author_id::text,
      approver_id::text,
      created_at::text
    FROM artifact_version
    WHERE artifact_version_id = ${artifactVersionId}::uuid
    LIMIT 1
  `);

  return row ? (row as unknown as ArtifactVersionRow) : undefined;
}

import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';
import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export async function upsertSearchDocument(
  db: Queryable,
  input: {
    caseId: string;
    streamId?: string;
    eventId: string;
    eventSeq: number;
    content: string;
    metadata?: Record<string, unknown>;
  }
): Promise<string> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO search_document (
      case_id, stream_id, event_id, event_seq, content, metadata, updated_at
    ) VALUES (
      ${input.caseId}::uuid,
      ${input.streamId ?? null},
      ${input.eventId}::uuid,
      ${input.eventSeq},
      ${input.content},
      ${JSON.stringify(input.metadata ?? {})}::jsonb,
      NOW()
    )
    ON CONFLICT (event_id) DO UPDATE SET
      case_id = EXCLUDED.case_id,
      stream_id = EXCLUDED.stream_id,
      event_seq = EXCLUDED.event_seq,
      content = EXCLUDED.content,
      metadata = EXCLUDED.metadata,
      updated_at = NOW()
    RETURNING doc_id::text
  `);

  return String((row as Record<string, unknown>).doc_id);
}

export async function upsertSearchEmbedding(
  db: Queryable,
  input: {
    docId: string;
    embedding: number[];
    embeddingModel?: string;
  }
): Promise<void> {
  await db.query(sql.typeAlias('void')`
    INSERT INTO search_embedding (doc_id, embedding, embedding_model, updated_at)
    VALUES (
      ${input.docId}::uuid,
      ${vectorLiteral(input.embedding)}::vector,
      ${input.embeddingModel ?? null},
      NOW()
    )
    ON CONFLICT (doc_id) DO UPDATE SET
      embedding = EXCLUDED.embedding,
      embedding_model = EXCLUDED.embedding_model,
      updated_at = NOW()
  `);
}

function vectorLiteral(values: number[]): string {
  return `[${values.join(',')}]`;
}

import { describe, expect, it, vi } from 'vitest';

import { TdbError } from '../src/errors/tdb_error.js';
import { SearchService } from '../src/services/search.service.js';

describe('SearchService', () => {
  it('delegates search.query to the gateway backend client', async () => {
    const backend = {
      searchQuery: vi.fn().mockResolvedValue([
        {
          doc_id: 'doc-1',
          case_id: 'case-1',
          stream_id: 'stream-a',
          event_id: 'event-1',
          event_seq: 7,
          content: 'alice reviewed the escalation packet',
          metadata: { source: 'test' },
          lexical_score: 0.9,
          vector_score: 0,
          hybrid_score: 0.9
        }
      ])
    };

    const service = new SearchService(backend as never);
    const hits = await service.query({
      query: 'alice escalation',
      stream_id: 'stream-a',
      limit: 5
    });

    expect(backend.searchQuery).toHaveBeenCalledWith({
      query: 'alice escalation',
      stream_id: 'stream-a',
      limit: 5
    });
    expect(hits).toEqual([
      {
        doc_id: 'doc-1',
        case_id: 'case-1',
        stream_id: 'stream-a',
        event_id: 'event-1',
        event_seq: 7,
        content: 'alice reviewed the escalation packet',
        metadata: { source: 'test' },
        lexical_score: 0.9,
        vector_score: 0,
        hybrid_score: 0.9
      }
    ]);
  });

  it('surfaces backend unavailability from the gateway backend client', async () => {
    const backend = {
      searchQuery: vi.fn().mockRejectedValue(
        new TdbError('BACKEND_UNAVAILABLE', 503, 'Search backend is unavailable')
      )
    };

    const service = new SearchService(backend as never);

    await expect(
      service.query({
        query: 'alice escalation'
      })
    ).rejects.toMatchObject({
      code: 'BACKEND_UNAVAILABLE',
      statusCode: 503
    });
  });
});

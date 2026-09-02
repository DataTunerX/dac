import { describe, expect, it, vi } from 'vitest';

import { IngestService } from '../src/services/ingest.service.js';

describe('IngestService', () => {
  it('does not require gateway embedding config for ingestText generate_embedding requests', async () => {
    const backend = {
      appendEvent: vi.fn().mockResolvedValue({
        event_id: 'evt-1',
        event_seq: 1,
        system_time: '2026-07-13T00:00:00Z'
      })
    };

    const service = new IngestService(
      backend as never
    );

    const response = await service.ingestText({
      stream_id: 'archeology-stream',
      generate_embedding: true,
      items: [
        {
          event_ref: 'event.1',
          text: 'Amun became central in New Kingdom royal ideology.'
        }
      ]
    });

    expect(response.accepted).toBe(1);
    expect(response.rejected).toBe(0);
    expect(backend.appendEvent).toHaveBeenCalledTimes(1);
    expect(backend.appendEvent).toHaveBeenCalledWith(expect.objectContaining({
      stream_id: 'archeology-stream',
      event_text: 'Amun became central in New Kingdom royal ideology.',
      embedding: undefined
    }));
  });
});

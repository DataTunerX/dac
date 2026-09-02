import { describe, expect, it, vi } from 'vitest';

import { MemoryService } from '../src/services/memory.service.js';
import { TdbError } from '../src/errors/tdb_error.js';

describe('MemoryService', () => {
  it('generates a non-empty entity_id when creating a new entity state', async () => {
    const backend = {
      listEntities: vi.fn().mockResolvedValue([]),
      upsertEntity: vi.fn().mockImplementation(async (request) => ({
        entity_id: request.entity_id,
        entity_type: request.entity_type,
        display_name: request.display_name,
        external_refs_json: request.external_refs_json,
        status: request.status,
        created_at: '2026-04-03T00:00:00Z',
        updated_at: '2026-04-03T00:00:00Z',
      })),
    };

    const service = new MemoryService(backend as never);
    const result = await service.upsertEntityState({
      entity_ref: {
        type: 'file',
        name: 'dac.json',
      },
      durable_state: {
        canonical_ref: 'file:dac-json',
        description: 'dac.json is the DAC config file.',
      },
    });

    expect(backend.upsertEntity).toHaveBeenCalledTimes(1);
    expect(backend.upsertEntity).toHaveBeenCalledWith(
      expect.objectContaining({
        entity_id: expect.stringMatching(
          /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
        ),
        entity_type: 'file',
        display_name: 'dac.json',
      }),
    );
    expect(result.status).toBe('created');
    expect(result.entity_id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
  });

  it('records a relation via backend edge upsert', async () => {
    const backend = {
      getEntity: vi.fn()
        .mockResolvedValueOnce({
          entity_id: '11111111-1111-4111-8111-111111111111',
          entity_type: 'machine',
          display_name: 'machine-a',
          external_refs_json: '{}',
          updated_at: '2026-04-03T00:00:00Z',
        })
        .mockResolvedValueOnce({
          entity_id: '22222222-2222-4222-8222-222222222222',
          entity_type: 'sensor',
          display_name: 'sensor-b',
          external_refs_json: '{}',
          updated_at: '2026-04-03T00:00:00Z',
        }),
      upsertEdge: vi.fn().mockResolvedValue({
        edge_state_id: 'edge-1',
        src_id: '11111111-1111-4111-8111-111111111111',
        predicate: 'feeds',
        dst_id: '22222222-2222-4222-8222-222222222222',
        valid_from: '2026-04-03T00:00:00.000Z',
        valid_to: null,
        system_from: '2026-04-03T00:00:01.000Z',
        system_to: null,
        source_event_id: null,
        confidence: 0.9,
      }),
    };

    const service = new MemoryService(backend as never);
    const result = await service.recordRelation({
      source_entity_id: '11111111-1111-4111-8111-111111111111',
      target_entity_id: '22222222-2222-4222-8222-222222222222',
      predicate: 'feeds',
      valid_from: '2026-04-03T00:00:00.000Z',
      confidence: 0.9,
    });

    expect(backend.upsertEdge).toHaveBeenCalledWith({
      src_id: '11111111-1111-4111-8111-111111111111',
      predicate: 'feeds',
      dst_id: '22222222-2222-4222-8222-222222222222',
      valid_from: '2026-04-03T00:00:00.000Z',
      system_from: undefined,
      source_event_id: undefined,
      confidence: 0.9,
    });
    expect(result).toEqual({
      edge_state_id: 'edge-1',
      source_entity_id: '11111111-1111-4111-8111-111111111111',
      predicate: 'feeds',
      target_entity_id: '22222222-2222-4222-8222-222222222222',
      valid_from: '2026-04-03T00:00:00.000Z',
      valid_to: undefined,
      system_from: '2026-04-03T00:00:01.000Z',
      system_to: undefined,
      source_event_id: undefined,
      confidence: 0.9,
    });
  });

  it('gets relations via backend edge lookup', async () => {
    const backend = {
      listEntities: vi.fn().mockResolvedValue([
        {
          entity_id: '11111111-1111-4111-8111-111111111111',
          entity_type: 'machine',
          display_name: 'machine-a',
          external_refs_json: '{}',
          updated_at: '2026-04-03T00:00:00Z',
        },
      ]),
      getEdgesAsOf: vi.fn().mockResolvedValue([
        {
          edge_state_id: 'edge-2',
          src_id: '11111111-1111-4111-8111-111111111111',
          predicate: 'monitors',
          dst_id: '22222222-2222-4222-8222-222222222222',
          valid_from: '2026-04-03T00:00:00.000Z',
          valid_to: null,
          system_from: '2026-04-03T00:00:01.000Z',
          system_to: null,
          source_event_id: null,
          confidence: null,
        },
      ]),
    };

    const service = new MemoryService(backend as never);
    const result = await service.getRelations({
      source_entity_ref: {
        type: 'machine',
        name: 'machine-a',
      },
      predicate: 'monitors',
      as_of_valid_time: '2026-04-03T00:00:00.000Z',
    });

    expect(backend.getEdgesAsOf).toHaveBeenCalledWith({
      src_id: '11111111-1111-4111-8111-111111111111',
      predicate: 'monitors',
      as_of_valid_time: '2026-04-03T00:00:00.000Z',
      as_of_system_time: undefined,
    });
    expect(result.relations).toHaveLength(1);
    expect(result.relations[0].predicate).toBe('monitors');
  });

  it('rejects the nil UUID when recording a relation', async () => {
    const service = new MemoryService({} as never);

    await expect(
      service.recordRelation({
        source_entity_id: '00000000-0000-0000-0000-000000000000',
        target_entity_ref: {
          type: 'sensor',
          name: 'sensor-z',
        },
        predicate: 'feeds',
        valid_from: '2026-04-03T00:00:00.000Z',
      }),
    ).rejects.toMatchObject({
      code: 'INVALID_ARGUMENT',
      message: expect.stringMatching(/nil UUID/i),
    } satisfies Partial<TdbError>);
  });
});

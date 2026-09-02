import type { Static } from '@sinclair/typebox';

import type { GatewayBackendClient, EntityRecord } from '../clients/gateway_backend.types.js';
import {
  EntityGetQuerySchema,
  EntityListQuerySchema,
  EntityUpsertRequestSchema
} from '../schema/v2/entity.js';

export type EntityUpsertRequest = Static<typeof EntityUpsertRequestSchema>;
export type EntityGetQuery = Static<typeof EntityGetQuerySchema>;
export type EntityListQuery = Static<typeof EntityListQuerySchema>;

export type EntityDto = {
  entity_id: string;
  entity_type: string;
  display_name: string;
  external_refs: Record<string, unknown>;
  status: 'active' | 'inactive' | 'deleted';
  created_at: string;
  updated_at: string;
};

export class EntityService {
  constructor(private readonly backend: GatewayBackendClient) {}

  async upsert(request: EntityUpsertRequest): Promise<EntityDto> {
    const record = await this.backend.upsertEntity({
      entity_id: request.entity_id ?? crypto.randomUUID(),
      entity_type: request.entity_type,
      display_name: request.display_name,
      external_refs_json: JSON.stringify(request.external_refs ?? {}),
      status: request.status ?? 'active'
    });
    return mapEntity(record);
  }

  async get(query: EntityGetQuery): Promise<EntityDto | undefined> {
    const record = await this.backend.getEntity({
      entity_id: query.entity_id
    });
    return record ? mapEntity(record) : undefined;
  }

  async list(query: EntityListQuery): Promise<EntityDto[]> {
    const records = await this.backend.listEntities({
      entity_type: query.entity_type,
      status: query.status,
      query: query.q,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapEntity);
  }
}

function mapEntity(record: EntityRecord): EntityDto {
  let external_refs: Record<string, unknown> = {};
  try {
    external_refs = JSON.parse(record.external_refs_json);
  } catch (e) {
    // Ignore
  }
  
  return {
    entity_id: record.entity_id,
    entity_type: record.entity_type,
    display_name: record.display_name,
    external_refs,
    status: record.status as any,
    created_at: record.created_at,
    updated_at: record.updated_at
  };
}

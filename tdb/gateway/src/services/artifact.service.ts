import type { Static } from '@sinclair/typebox';

import type {
  GatewayBackendClient,
  ArtifactRecord,
  ArtifactVersionRecord
} from '../clients/gateway_backend.types.js';
import {
  ArtifactCreateRequestSchema,
  ArtifactVersionAsOfQuerySchema,
  ArtifactVersionCreateRequestSchema
} from '../schema/v2/artifact.js';

export type ArtifactCreateRequest = Static<typeof ArtifactCreateRequestSchema>;
export type ArtifactVersionCreateRequest = Static<typeof ArtifactVersionCreateRequestSchema>;
export type ArtifactVersionAsOfQuery = Static<typeof ArtifactVersionAsOfQuerySchema>;

export type ArtifactDto = {
  artifact_id: string;
  artifact_type: string;
  name: string;
  description?: string;
  created_at: string;
};

export type ArtifactVersionDto = {
  artifact_version_id: string;
  artifact_id: string;
  version_number: number;
  status: string;
  valid_from: string;
  valid_to?: string;
  system_from: string;
  system_to?: string;
  content_ref: string;
  content_hash?: string;
  author_id?: string;
  approver_id?: string;
  created_at: string;
};

export class ArtifactService {
  constructor(private readonly backend: GatewayBackendClient) {}

  async createArtifact(request: ArtifactCreateRequest): Promise<ArtifactDto> {
    const record = await this.backend.createArtifact({
      artifact_type: request.artifact_type,
      name: request.name,
      description: request.description ?? ''
    });
    return mapArtifact(record);
  }

  async createArtifactVersion(request: ArtifactVersionCreateRequest): Promise<ArtifactVersionDto> {
    const record = await this.backend.createArtifactVersion({
      artifact_id: request.artifact_id,
      version_number: request.version_number,
      status: request.status,
      valid_from: request.valid_from,
      valid_to: request.valid_to ?? '',
      system_from: request.system_from ?? new Date().toISOString(),
      content_ref: request.content_ref,
      content_hash: request.content_hash ?? '',
      author_id: request.author_id ?? '',
      approver_id: request.approver_id ?? ''
    });
    return mapArtifactVersion(record);
  }

  async getArtifactVersionAsOf(query: ArtifactVersionAsOfQuery): Promise<ArtifactVersionDto | undefined> {
    const record = await this.backend.getArtifactVersionAsOf({
      artifact_id: query.artifact_id,
      as_of_valid_time: query.as_of_valid_time
    });
    return record ? mapArtifactVersion(record) : undefined;
  }
}

function mapArtifact(record: ArtifactRecord): ArtifactDto {
  return {
    artifact_id: record.artifact_id,
    artifact_type: record.artifact_type,
    name: record.name,
    description: record.description || undefined,
    created_at: record.created_at
  };
}

function mapArtifactVersion(record: ArtifactVersionRecord): ArtifactVersionDto {
  return {
    artifact_version_id: record.artifact_version_id,
    artifact_id: record.artifact_id,
    version_number: record.version_number,
    status: record.status,
    valid_from: record.valid_from,
    valid_to: record.valid_to || undefined,
    system_from: record.system_from,
    system_to: record.system_to || undefined,
    content_ref: record.content_ref,
    content_hash: record.content_hash || undefined,
    author_id: record.author_id || undefined,
    approver_id: record.approver_id || undefined,
    created_at: record.created_at
  };
}

import type { Static } from '@sinclair/typebox';

import type {
  DomainStreamBindingListQuery,
  DomainStreamBindingRecord,
  DomainStreamBindingUpsertRequest,
  GatewayBackendClient
} from '../clients/gateway_backend.types.js';
import { SearchQueryRequestSchema } from '../schema/v2/search.js';

export type SearchQueryRequest = Static<typeof SearchQueryRequestSchema>;

export type SearchHit = {
  doc_id: string;
  case_id: string;
  stream_id?: string;
  event_id: string;
  event_seq: number;
  content: string;
  metadata: Record<string, unknown>;
  lexical_score: number;
  vector_score: number;
  hybrid_score: number;
};

export type SearchQueryResult = {
  hits: SearchHit[];
  resolved_stream_ids: string[];
};

export type SearchDomainStreamBindingDto = DomainStreamBindingRecord;

export class SearchService {
  constructor(private readonly gatewayBackend: GatewayBackendClient) {}

  async query(request: SearchQueryRequest): Promise<SearchQueryResult> {
    return this.gatewayBackend.searchQuery(request);
  }

  async upsertDomainStreamBinding(
    request: DomainStreamBindingUpsertRequest
  ): Promise<SearchDomainStreamBindingDto> {
    return this.gatewayBackend.upsertDomainStreamBinding(request);
  }

  async listDomainStreamBindings(
    query: DomainStreamBindingListQuery
  ): Promise<SearchDomainStreamBindingDto[]> {
    return this.gatewayBackend.listDomainStreamBindings(query);
  }
}

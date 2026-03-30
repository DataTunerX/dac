import json
from pydantic import BaseModel, ConfigDict
from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
import uuid
from datetime import datetime

# vector section
class DocumentModel(BaseModel):
    page_content: str
    metadata: dict = {}

class SearchType(str, Enum):
    VECTOR = "vector"
    FULLTEXT = "fulltext"
    HYBRID = "hybrid"
    MEMORY = "memory"
    KG = "kg"

class CreateRequest(BaseModel):
    documents: List[DocumentModel]
    collection_name: str

class MetadataRequest(BaseModel):
    collection_names: List[str]

class AddTextsRequest(BaseModel):
    documents: List[DocumentModel]
    collection_name: str

class SearchRequest(BaseModel):
    query: str
    collection_name: str
    search_type: SearchType = SearchType.VECTOR
    top_k: int = 2
    fulltext_weight: Optional[float] = 0.5
    vector_weight: Optional[float] = 0.5
    kg_hop_limit: Optional[int] = 2

class DeleteRequest(BaseModel):
    collection_name: str

## memory section
class MemoryMessage(BaseModel):
    role: str
    content: str

class MemoryAddRequest(BaseModel):
    messages: List[MemoryMessage]
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class MemoryUpdateRequest(BaseModel):
    data: str

class MemorySearchRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    limit: int = 100

class MemoryGetAllRequest(BaseModel):
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    limit: int = 100

class MemoryDeleteRequest(BaseModel):
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None

class MemoryResponse(BaseModel):
    status: str
    message: str
    data: Optional[Dict] = None


## knowledge pyramid
class KnowledgePyramidAddRequest(BaseModel):
    documents: List[DocumentModel]

class KnowledgePyramidSearchRequest(BaseModel):
    query: str
    search_type: SearchType = SearchType.VECTOR
    limit: int = 10
    hybrid_threshold: float = 0.1
    fulltext_weight: Optional[float] = 0.5
    vector_weight: Optional[float] = 0.5

class KnowledgePyramidDeleteRequest(BaseModel):
    documents: List[str]

## vector
class VectorAddDocumentsRequest(BaseModel):
    documents: List[DocumentModel]

class VectorSearchRequest(BaseModel):
    query: str
    search_type: SearchType = SearchType.VECTOR
    limit: int = 10
    hybrid_threshold: float = 0.1
    fulltext_weight: Optional[float] = 0.5
    vector_weight: Optional[float] = 0.5

class VectorDeleteDocumentsRequest(BaseModel):
    documents: List[str]

class VectorDeleteDocumentsByMetaFieldRequest(BaseModel):
    key: str
    value: str


class VectorGetIdsByMetaFieldRequest(BaseModel):
    key: str
    value: str


class VectorGetIdsByMetaFieldResponse(BaseModel):
    ids: List[str] = Field(default_factory=list, description="Document ids matching the metadata key-value")


class VectorCreateCollectionRequest(BaseModel):
    documents: List[DocumentModel]
    collection_name: str

class VectorDeleteCollectionRequest(BaseModel):
    collection_name: str


# signature

class Signature(BaseModel):
    sig_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Primary key")
    sig_type: str = Field(..., description="Signature type: application, database, api, file_system")
    discovery_mode: str = Field(..., description="Discovery mode: auto, manual")
    fingerprint: str = Field(..., description="Fingerprint hash for change detection")
    location_info: Optional[Dict[str, Any]] = Field(None, description="Location information (IP, URL, DB_Instance, etc.)")
    metadata_content: Optional[Dict[str, Any]] = Field(None, description="Metadata content (table structure, fields, types, etc.)")
    dd_namespace: Optional[str] = Field(None, description="DD namespace")
    dd_name: Optional[str] = Field(None, description="DD name")
    created_at: Optional[datetime] = Field(None, description="Creation time")
    updated_at: Optional[datetime] = Field(None, description="Update time")

class SignatureCreateRequest(BaseModel):
    sig_type: str = Field(..., description="Signature type: application, database, api, file_system")
    discovery_mode: str = Field(..., description="Discovery mode: auto, manual")
    fingerprint: str = Field(..., description="Fingerprint hash for change detection")
    location_info: Optional[Dict[str, Any]] = Field(None, description="Location information")
    metadata_content: Optional[Dict[str, Any]] = Field(None, description="Metadata content")
    dd_namespace: Optional[str] = Field(None, description="DD namespace")
    dd_name: Optional[str] = Field(None, description="DD name")

class SignatureUpdateRequest(BaseModel):
    sig_type: Optional[str] = Field(None, description="Signature type")
    discovery_mode: Optional[str] = Field(None, description="Discovery mode")
    fingerprint: Optional[str] = Field(None, description="Fingerprint hash")
    location_info: Optional[Dict[str, Any]] = Field(None, description="Location information")
    metadata_content: Optional[Dict[str, Any]] = Field(None, description="Metadata content")
    dd_namespace: Optional[str] = Field(None, description="DD namespace")
    dd_name: Optional[str] = Field(None, description="DD name")

class SignatureResponse(BaseModel):
    status: str
    data: Optional[Any] = None
    message: Optional[str] = None
    count: Optional[int] = None

class SignatureSearchByDDRequest(BaseModel):
    dd_namespace: str
    dd_name: str

class SignatureListResponse(BaseModel):
    status: str
    data: List[Signature]
    count: int

# codebase indexer

class CodebaseIndexer(BaseModel):
    codebase_indexer_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Primary key")
    filepath: Optional[str] = Field(None, description="Code filepath")
    code_deep_analysis: Optional[str] = Field(None, description="Code deep analysis")
    dd_namespace: Optional[str] = Field(None, description="DD namespace")
    dd_name: Optional[str] = Field(None, description="DD name")
    created_at: Optional[datetime] = Field(None, description="Creation time")
    updated_at: Optional[datetime] = Field(None, description="Update time")

class CodebaseIndexerCreateRequest(BaseModel):
    codebase_indexer_id: Optional[str] = Field(None, description="Codebase indexer ID (auto-generated if not provided)")
    filepath: Optional[str] = Field(None, description="Code filepath")
    code_deep_analysis: Optional[str] = Field(None, description="Code deep analysis")
    dd_namespace: Optional[str] = Field(None, description="DD namespace")
    dd_name: Optional[str] = Field(None, description="DD name")

class CodebaseIndexerUpdateRequest(BaseModel):
    filepath: Optional[str] = Field(None, description="Code filepath")
    code_deep_analysis: Optional[str] = Field(None, description="Code deep analysis")
    dd_namespace: Optional[str] = Field(None, description="DD namespace")
    dd_name: Optional[str] = Field(None, description="DD name")

class CodebaseIndexerResponse(BaseModel):
    status: str
    data: Optional[Any] = None
    message: Optional[str] = None
    count: Optional[int] = None

class CodebaseIndexerSearchByDDRequest(BaseModel):
    dd_namespace: str
    dd_name: str

class CodebaseIndexerSearchByFilepathRequest(BaseModel):
    filepath: str
    dd_namespace: Optional[str] = None
    dd_name: Optional[str] = None
    prefix_match: bool = False  # If True, use LIKE query for prefix matching

class CodebaseIndexerListResponse(BaseModel):
    status: str
    data: List[CodebaseIndexer]
    count: int


# semantic domain

class SemanticDomain(BaseModel):
    semantic_domain_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Primary key")
    semantic_domain: Optional[str] = Field(None, description="Semantic domain from analysis")
    agent_card: Optional[str] = Field(None, description="Agent card information for agent creation")
    dd_namespace: Optional[str] = Field(None, description="DD namespace")
    dd_name: Optional[str] = Field(None, description="DD name")
    descriptor_type: Optional[str] = Field(None, description="Descriptor type (code/structured/unstructured)")
    version: Optional[str] = Field(None, description="Version, incremented on each update")
    created_at: Optional[datetime] = Field(None, description="Creation time")
    updated_at: Optional[datetime] = Field(None, description="Update time")

class SemanticDomainCreateRequest(BaseModel):
    semantic_domain_id: Optional[str] = Field(None, description="Semantic domain ID (auto-generated if not provided)")
    semantic_domain: Optional[str] = Field(None, description="Semantic domain")
    agent_card: Optional[str] = Field(None, description="Agent card information")
    dd_namespace: Optional[str] = Field(None, description="DD namespace")
    dd_name: Optional[str] = Field(None, description="DD name")
    descriptor_type: Optional[str] = Field(None, description="Descriptor type (code/structured/unstructured)")
    version: Optional[str] = Field(None, description="Version (default '1' for new records)")

class SemanticDomainUpdateRequest(BaseModel):
    semantic_domain_id: Optional[str] = Field(None, description="SemanticDomain type")
    semantic_domain: Optional[str] = Field(None, description="Semantic domain")
    agent_card: Optional[str] = Field(None, description="Agent card information")
    dd_namespace: Optional[str] = Field(None, description="DD namespace")
    dd_name: Optional[str] = Field(None, description="DD name")
    descriptor_type: Optional[str] = Field(None, description="Descriptor type (code/structured/unstructured)")
    version: Optional[str] = Field(None, description="Version, incremented on each update")

class SemanticDomainResponse(BaseModel):
    status: str
    data: Optional[Any] = None
    message: Optional[str] = None
    count: Optional[int] = None

class SemanticDomainSearchByDDRequest(BaseModel):
    dd_namespace: str
    dd_name: str

class SemanticDomainListResponse(BaseModel):
    status: str
    data: List[SemanticDomain]
    count: int


# semantic group
class SemanticGroup(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Primary key")
    group_name: str = Field(..., description="Group name")
    description: Optional[str] = Field(None, description="Group description")
    agent_card: Optional[str] = Field(None, description="Agent Card")
    version: Optional[str] = Field(None, description="Version, incremented on each update")
    parent_id: Optional[str] = Field(None, description="Parent group ID (NULL = root or leaf)")
    created_at: Optional[datetime] = Field(None, description="Creation time")
    updated_at: Optional[datetime] = Field(None, description="Update time")

class DDGroupRelation(BaseModel):
    id: Optional[int] = Field(None, description="Primary key (auto-increment)")
    sd_id: str = Field(..., description="Semantic domain ID")
    group_id: str = Field(..., description="Group ID")
    association_reason: Optional[str] = Field(None, description="Reason for association")

class SemanticGroupCreateRequest(BaseModel):
    id: Optional[str] = Field(None, description="Group ID (auto-generated if not provided)")
    group_name: str = Field(..., description="Group name")
    description: Optional[str] = Field(None, description="Group description")
    agent_card: Optional[str] = Field(None, description="Agent Card")
    version: Optional[str] = Field(None, description="Version (default '1' for new records)")
    parent_id: Optional[str] = Field(None, description="Parent group ID")

class SemanticGroupUpdateRequest(BaseModel):
    group_name: Optional[str] = Field(None, description="Group name")
    description: Optional[str] = Field(None, description="Group description")
    agent_card: Optional[str] = Field(None, description="Agent Card")
    version: Optional[str] = Field(None, description="Version, incremented on each update")
    parent_id: Optional[str] = Field(None, description="Parent group ID")

class DDGroupRelationCreateRequest(BaseModel):
    sd_id: str = Field(..., description="Semantic domain ID")
    group_id: str = Field(..., description="Group ID")
    association_reason: Optional[str] = Field(None, description="Reason for association")


class DDGroupRelationUpdateRequest(BaseModel):
    association_reason: Optional[str] = Field(None, description="Updated association reason")


class SemanticGroupResponse(BaseModel):
    status: str
    data: Optional[Any] = None
    message: Optional[str] = None
    count: Optional[int] = None

class SemanticGroupListResponse(BaseModel):
    status: str
    data: List[SemanticGroup]
    count: int

class DDGroupRelationListResponse(BaseModel):
    status: str
    data: List[DDGroupRelation]
    count: int


class SemanticGroupMemberDetail(BaseModel):
    """Semantic domain member in a group: relation info + full semantic domain details."""
    relation: DDGroupRelation = Field(..., description="Group-SD relation (sd_id, group_id, association_reason)")
    semantic_domain: Optional[SemanticDomain] = Field(None, description="Semantic domain details (None if SD was deleted)")


class SemanticGroupInfo(BaseModel):
    """Summary info of a child group within a parent group."""
    id: str = Field(..., description="Child group ID")
    group_name: str = Field(..., description="Child group name")
    description: Optional[str] = Field(None, description="Child group description")
    agent_card: Optional[str] = Field(None, description="Child group Agent Card JSON")


class SemanticGroupWithMembersData(BaseModel):
    """Semantic group with its member semantic domains and child groups."""
    group: SemanticGroup = Field(..., description="The semantic group")
    members: List[SemanticGroupMemberDetail] = Field(default_factory=list, description="Member semantic domains with details")
    child_groups: List[SemanticGroupInfo] = Field(default_factory=list, description="Child groups (non-leaf groups have these instead of SD members)")


class SemanticGroupWithMembersResponse(BaseModel):
    status: str
    data: Optional[SemanticGroupWithMembersData] = None
    message: Optional[str] = None


# conversation history
class HistoryRecord(BaseModel):
    hid: str = Field(..., description="Primary key")
    user_id: str = Field(..., description="User ID")
    agent_id: str = Field(..., description="Agent ID")
    run_id: Optional[str] = Field(None, description="Run ID")
    conversation: Optional[str] = Field(None, description="Conversation record (role, content only)")
    think: Optional[str] = Field(None, description="Think content per message (JSON array)")
    created_at: Optional[datetime] = Field(None, description="Creation time")
    updated_at: Optional[datetime] = Field(None, description="Update time")

class HistoryMessage(BaseModel):
    role: str
    content: str
    think: Optional[str] = None

class CreateHistoryRequest(BaseModel):
    user_id: str
    agent_id: str
    run_id: str
    messages: List[HistoryMessage]

    def get_conversation_json(self) -> str:
        """Conversation without think (role, content only)."""
        return json.dumps([{"role": m.role, "content": m.content} for m in self.messages], ensure_ascii=False)

    def get_think_json(self) -> str:
        """Think values in same order as messages."""
        return json.dumps([(m.think or "") for m in self.messages], ensure_ascii=False)

class CreateHistoryResponse(BaseModel):
    status: str
    hid: Optional[str] = None
    message: str

class SearchHistoryRequest(BaseModel):
    user_id: str
    agent_id: str
    run_id: str
    limit: Optional[int] = None

class SearchHistoryRequestByUserAndRun(BaseModel):
    user_id: str
    run_id: str
    limit: Optional[int] = None

class HistoryRecordResponse(BaseModel):
    hid: str
    user_id: str
    agent_id: str
    run_id: str
    messages: List[HistoryMessage]
    think: Optional[List[str]] = None  # think per message, same order as messages
    created_at: datetime
    updated_at: datetime

class SearchHistoryResponse(BaseModel):
    status: str
    data: List[HistoryRecordResponse]
    total: int
    message: str

## knowledge graph section
class KnowledgeGraphNode(BaseModel):
    model_config = ConfigDict(extra='allow')  # 允许额外字段，支持节点顶层的name等字段
    id: str
    labels: List[str]
    properties: Dict[str, Any] = {}

class KnowledgeGraphRelationship(BaseModel):
    start: str
    end: str
    type: str
    properties: Dict[str, Any] = {}

class KnowledgeGraphAddRequest(BaseModel):
    source: str
    nodes: List[KnowledgeGraphNode]
    relationships: List[KnowledgeGraphRelationship] = []
    clear_existing: bool = False

class KnowledgeGraphSearchRequest(BaseModel):
    source: str
    query_text: Optional[str] = None  # 向量搜索查询文本
    node_id: Optional[str] = None
    label: Optional[str] = None
    property_name: Optional[str] = None
    property_value: Optional[Any] = None
    limit: int = 100
    top_k: Optional[int] = 10  # 向量搜索返回的最相似节点数量
    include_relationships: Optional[bool] = True  # 是否包含关系信息
    relationship_depth: Optional[int] = 1  # 关系查询深度
    return_svo_only: Optional[bool] = False  # 是否只返回SVO格式的字符串（仅对向量搜索有效）

class KnowledgeGraphDeleteRequest(BaseModel):
    source: str

class KnowledgeGraphGetGraphRequest(BaseModel):
    """按 source 查询整图（所有节点 + 所有关系）的请求"""
    source: str
    node_limit: int = 10000
    rel_limit: int = 10000

class KnowledgeGraphResponse(BaseModel):
    status: str
    message: str
    data: Optional[Dict[str, Any]] = None

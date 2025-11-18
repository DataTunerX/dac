import json
from pydantic import BaseModel
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
    memory_threshold: float = 0.1
    fulltext_weight: Optional[float] = 0.5
    vector_weight: Optional[float] = 0.5

class KnowledgePyramidDeleteRequest(BaseModel):
    documents: List[str]
    memorys: Optional[List[str]]

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

class VectorCreateCollectionRequest(BaseModel):
    documents: List[DocumentModel]
    collection_name: str

class VectorDeleteCollectionRequest(BaseModel):
    collection_name: str


# fingerprint

class Fingerprint(BaseModel):
    fid: str = Field(default_factory=lambda: str(uuid.uuid4()))
    fingerprint_id: str
    fingerprint_summary: str
    agent_info_name: str
    agent_info_description: str
    dd_namespace: str
    dd_name: str

class FingerprintCreateRequest(BaseModel):
    fingerprint_id: str
    fingerprint_summary: str
    agent_info_name: str
    agent_info_description: str
    dd_namespace: str
    dd_name: str

class FingerprintUpdateRequest(BaseModel):
    fingerprint_id: str
    fingerprint_summary: str
    agent_info_name: str
    agent_info_description: str
    dd_namespace: str
    dd_name: str

class FingerprintResponse(BaseModel):
    status: str
    data: Optional[Any] = None
    message: Optional[str] = None
    count: Optional[int] = None

class FingerprintSearchByDDRequest(BaseModel):
    dd_namespace: str
    dd_name: str

class FingerprintListResponse(BaseModel):
    status: str
    data: List[Fingerprint]
    count: int

# conversation history
class HistoryRecord(BaseModel):
    hid: str = Field(..., description="Primary key")
    user_id: str = Field(..., description="User ID")
    agent_id: str = Field(..., description="Agent ID")
    run_id: Optional[str] = Field(None, description="Run ID")
    conversation: Optional[str] = Field(None, description="Conversation record")
    created_at: Optional[datetime] = Field(None, description="Creation time")
    updated_at: Optional[datetime] = Field(None, description="Update time")

class HistoryMessage(BaseModel):
    role: str
    content: str

class CreateHistoryRequest(BaseModel):
    user_id: str
    agent_id: str
    run_id: str
    messages: List[HistoryMessage]

    def get_messages_json(self) -> str:
        return json.dumps([msg.model_dump() for msg in self.messages], ensure_ascii=False)

class CreateHistoryResponse(BaseModel):
    status: str
    hid: Optional[str] = None
    message: str

class SearchHistoryRequest(BaseModel):
    user_id: str
    agent_id: str
    run_id: str
    limit: Optional[int] = None

class HistoryRecordResponse(BaseModel):
    hid: str
    user_id: str
    agent_id: str
    run_id: str
    messages: List[HistoryMessage]
    created_at: datetime
    updated_at: datetime

class SearchHistoryResponse(BaseModel):
    status: str
    data: List[HistoryRecordResponse]
    total: int
    message: str

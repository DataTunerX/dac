from pydantic import BaseModel, Field

class DocumentModel(BaseModel):
    page_content: str
    metadata: dict = {}

class Fingerprint(BaseModel):
    fid: str
    fingerprint_id: str
    fingerprint_summary: str
    agent_info_name: str
    agent_info_description: str
    dd_namespace: str
    dd_name: str
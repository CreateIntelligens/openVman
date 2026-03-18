"""Pydantic schemas for API requests and responses."""

from typing import Any
from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    project_id: str = Field(..., description="Unique ID for the project")
    label: str = Field(..., description="Display label for the project")


class ProjectDeleteRequest(BaseModel):
    project_id: str = Field(..., description="ID of the project to delete")


class PersonaCreateRequest(BaseModel):
    persona_id: str = Field(..., description="Unique ID for the persona")
    label: str = Field(..., description="Display label for the persona")
    project_id: str = Field("default", description="Project this persona belongs to")


class PersonaDeleteRequest(BaseModel):
    persona_id: str = Field(..., description="ID of the persona to delete")
    project_id: str = Field("default", description="Project ID")


class PersonaCloneRequest(BaseModel):
    source_persona_id: str = Field(..., description="Original persona ID")
    target_persona_id: str = Field(..., description="New persona ID")
    project_id: str = Field("default", description="Project ID")


class ProtocolValidateRequest(BaseModel):
    direction: str = Field(..., pattern="^(client_to_server|server_to_client)$")
    payload: dict[str, Any]
    version: str = "1.0.0"


class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1)


class SearchRequest(BaseModel):
    query: str = Field(..., description="Semantic search query")
    table: str = Field("memories", pattern="^(knowledge|memories)$")
    top_k: int = 5
    query_type: str = Field("vector", pattern="^(vector|hybrid)$")
    project_id: str = "default"
    persona_id: str = "default"


class AddMemoryRequest(BaseModel):
    text: str = Field(..., description="Content to remember")
    source: str = "user"
    project_id: str = "default"
    persona_id: str = "default"
    metadata: dict[str, Any] = {}


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message content")
    project_id: str = "default"
    persona_id: str = "default"
    session_id: str | None = None
    metadata: dict[str, Any] = {}


class KnowledgeDocumentPutRequest(BaseModel):
    path: str = Field(..., description="Relative path in workspace")
    content: str = Field(..., description="Full text content")
    project_id: str = "default"


class KnowledgeDocumentMoveRequest(BaseModel):
    source_path: str
    target_path: str
    project_id: str = "default"


class KnowledgeIngestRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Text content to ingest")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Source metadata (source_url, etc.)")
    project_id: str = "default"


class AdminActionRequest(BaseModel):
    project_id: str = "default"

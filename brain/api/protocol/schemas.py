"""Pydantic schemas for API requests and responses."""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ProjectCreateRequest(BaseModel):
    label: str = Field(..., min_length=1, description="專案名稱")

    @field_validator("label")
    @classmethod
    def label_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("專案名稱不可為空白")
        return v


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


class InternalEnrichRequest(BaseModel):
    trace_id: str = ""
    session_id: str | None = None
    enriched_context: list[dict[str, Any]] = Field(default_factory=list)
    media_refs: list[dict[str, Any]] = Field(default_factory=list)
    project_id: str = "default"
    persona_id: str = "default"


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


class KnowledgeDocumentMetaPatchRequest(BaseModel):
    path: str = Field(..., description="Relative path in workspace")
    project_id: str = "default"
    enabled: bool | None = None
    source_type: str | None = Field(None, pattern="^(upload|web|manual)$")
    source_url: str | None = None


class KnowledgeNoteCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, description="Note title")
    content: str = Field(..., min_length=1, description="Note content")
    project_id: str = "default"

    @field_validator("title", "content")
    @classmethod
    def note_fields_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("欄位不可為空白")
        return value


class AdminActionRequest(BaseModel):
    project_id: str = "default"


class SkillCreateRequest(BaseModel):
    skill_id: str = Field(..., min_length=1, description="Unique skill identifier")
    name: str = Field(..., min_length=1, description="Display name")
    description: str = Field("", description="Skill description")


class SkillFilesUpdateRequest(BaseModel):
    files: dict[str, str] = Field(..., description="Map of filename → content")

from contextvars import ContextVar

active_persona_id: ContextVar[str] = ContextVar("brain_active_persona_id", default="default")
active_project_id: ContextVar[str] = ContextVar("brain_active_project_id", default="default")
active_user_message: ContextVar[str] = ContextVar("brain_active_user_message", default="")

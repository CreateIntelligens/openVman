"""Classify streaming-ASR speech while the browser plays a reply."""

import unicodedata
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import CurrentAccount, get_current_account
from app.guard_agent import GuardAgent

router = APIRouter(prefix="/api/v1/voice", tags=["Voice"])
_guard = GuardAgent()


class InterruptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transcript: str = Field(min_length=1, max_length=2000)
    reply_text: str = Field(default="", max_length=100000)


def _normalized(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKC", text).casefold()
        if char.isalnum()
    )


@router.post("/interrupt")
async def classify_interrupt(
    body: InterruptRequest,
    current: CurrentAccount = Depends(get_current_account),
) -> dict[str, Literal["STOP", "IGNORE"]]:
    transcript = _normalized(body.transcript)
    # A transcript wholly contained in the reply is likely speaker echo.
    # This is deliberately conservative: identical user repetitions also pass.
    if not transcript or transcript in _normalized(body.reply_text):
        return {"action": "IGNORE"}
    return {"action": await _guard.classify(body.transcript)}

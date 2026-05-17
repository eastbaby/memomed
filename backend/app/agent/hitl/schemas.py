from typing import Any, Literal

from pydantic import BaseModel, Field


class SelectOption(BaseModel):
    label: str
    value: str


class InteractionRequest(BaseModel):
    type: Literal["select_one", "confirm", "text_input"]
    title: str
    description: str | None = None
    options: list[SelectOption] = Field(default_factory=list)
    placeholder: str | None = None
    pending_action: dict[str, Any] | None = None

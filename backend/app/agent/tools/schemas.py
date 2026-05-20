from typing import Any, Literal

from pydantic import BaseModel, model_validator

from app.agent.hitl.schemas import InteractionRequest


ToolStatus = Literal[
    "success",
    "needs_user_confirmation",
    "needs_user_selection",
    "needs_user_input",
    "already_satisfied",
    "capability_missing",
    "not_applicable",
    "error",
]


class PendingAction(BaseModel):
    id: str
    type: str
    continuation_tool: str
    candidate_payload: dict[str, Any] = {}


class ToolResult(BaseModel):
    status: ToolStatus
    message: str
    data: dict[str, Any] = {}
    pending_action: PendingAction | None = None
    interaction: InteractionRequest | None = None

    @model_validator(mode="after")
    def validate_interaction_contract(self) -> "ToolResult":
        if self.status in {"needs_user_confirmation", "needs_user_selection"}:
            if self.pending_action is None:
                raise ValueError(f"{self.status} requires pending_action")
            if self.interaction is None:
                raise ValueError(f"{self.status} requires interaction")
        if self.status == "needs_user_input" and self.interaction is None:
            raise ValueError("needs_user_input requires interaction")
        return self

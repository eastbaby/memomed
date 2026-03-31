from typing import Any, Literal
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# HITL 数据合同模型：与前端 agent-chat-ui 的 HITLRequest TypeScript 接口保持一致
# 前端定义：agent-chat-ui/src/components/thread/agent-inbox/types.ts
# ---------------------------------------------------------------------------

DecisionType = Literal["approve", "edit", "reject"]


class HITLActionRequest(BaseModel):
    """HITLRequest 中的单个动作请求。

    对应前端 ActionRequest 接口：
        name: string;
        args: Record<string, unknown>;
        description?: string;
    """

    name: str
    args: dict[str, Any]
    description: str | None = None


class HITLReviewConfig(BaseModel):
    """HITLRequest 中的审批配置，控制该动作可用的决策类型和可编辑字段。

    对应前端 ReviewConfig 接口：
        action_name: string;
        allowed_decisions: DecisionType[];
        args_schema?: Record<string, unknown>;
    """

    action_name: str
    allowed_decisions: list[DecisionType]
    args_schema: dict[str, Any] | None = None


class HITLRequest(BaseModel):
    """LangGraph interrupt() 的标准输出格式，与前端 agent-chat-ui 的 HITLRequest 双向对齐。

    对应前端 HITLRequest 接口：
        action_requests: ActionRequest[];
        review_configs: ReviewConfig[];
    """

    action_requests: list[HITLActionRequest]
    review_configs: list[HITLReviewConfig]


# ---------------------------------------------------------------------------
# HITL 决策模型：当 resume 时前端返回的数据结构
# 前端定义：agent-chat-ui/agent-inbox/hooks/use-interrupted-actions.tsx resumeRun()
# ---------------------------------------------------------------------------

class HITLEditedAction(BaseModel):
    """edit 类型决策中带的修改后动作。

    对应前端 Action 接口：
        name: string;
        args: Record<string, unknown>;
    """

    name: str
    args: dict[str, Any]


class HITLDecision(BaseModel):
    """agent-inbox resume 时返回的单个决策。

    对应前端 Decision 类型：
        | { type: 'approve' }
        | { type: 'reject'; message?: string }
        | { type: 'edit'; edited_action: Action }
    """

    type: DecisionType
    action_name: str | None = None  # agent-inbox 会携带此字段设定属于哪个动作
    message: str | None = None  # reject 时的可选说明
    edited_action: HITLEditedAction | None = None  # edit 时的修改内容


class HITLResumePayload(BaseModel):
    """agent-inbox 调用 resumeRun() 时的完整 payload。

    对应前端定义 (use-interrupted-actions.tsx)：
        thread.submit({}, { command: { resume: { decisions } } })
    """

    decisions: list[HITLDecision]

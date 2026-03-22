from typing import Annotated
from typing_extensions import TypedDict
import operator


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    user_input: str
    response: str
    metadata: dict
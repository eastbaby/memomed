from typing import Annotated, Literal
from typing_extensions import TypedDict
import operator


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    question_message_content: list
    human_image_list: list
    human_image_store_list: list[Literal["store_success", "store_failed", "store_pending", "no_store"]]
    answer_keypoints: list[str]
    response: str
    metadata: dict

from langgraph.graph import StateGraph, START, END
from app.agent.utils.state import AgentState
from app.agent.utils.nodes import (
    process_input,
    route_after_process_input,
    confirm_report_uploads,
    route_after_confirm_report_uploads,
    prepare_report_uploads,
    route_after_prepare_report_uploads,
    notify_metadata_confirmation,
    confirm_report_metadata,
    route_after_confirm_report_metadata,
    finalize_report_uploads,
    call_model,
    tools_condition,
    generate_response,
    tool_node,
)


graph = (
    StateGraph(AgentState)
    .add_node("process_input", process_input)
    .add_node("confirm_report_uploads", confirm_report_uploads)
    .add_node("prepare_report_uploads", prepare_report_uploads)
    .add_node("notify_metadata_confirmation", notify_metadata_confirmation)
    .add_node("confirm_report_metadata", confirm_report_metadata)
    .add_node("finalize_report_uploads", finalize_report_uploads)
    .add_node("call_model", call_model)
    .add_node("tools", tool_node)
    .add_node("generate_response", generate_response)
    .add_edge(START, "process_input")
    .add_conditional_edges(
        "process_input",
        route_after_process_input,
        {
            "confirm_report_uploads": "confirm_report_uploads",
            "prepare_report_uploads": "prepare_report_uploads",
            "call_model": "call_model",
        },
    )
    .add_conditional_edges(
        "confirm_report_uploads",
        route_after_confirm_report_uploads,
        {
            "prepare_report_uploads": "prepare_report_uploads",
            "call_model": "call_model",
        },
    )
    .add_conditional_edges(
        "prepare_report_uploads",
        route_after_prepare_report_uploads,
        {
            "notify_metadata_confirmation": "notify_metadata_confirmation",
            "finalize_report_uploads": "finalize_report_uploads",
        },
    )
    .add_edge("notify_metadata_confirmation", "confirm_report_metadata")
    .add_conditional_edges(
        "confirm_report_metadata",
        route_after_confirm_report_metadata,
        {
            "finalize_report_uploads": "finalize_report_uploads",
            "call_model": "call_model",
        },
    )
    .add_edge("finalize_report_uploads", "call_model")
    .add_conditional_edges("call_model", tools_condition, {"tools": "tools", "end": "generate_response"})
    .add_edge("tools", "call_model")
    .add_edge("generate_response", END)
    .compile(name="memomed_agent")
)

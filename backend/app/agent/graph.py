from langgraph.graph import StateGraph, START, END
from app.agent.utils.state import AgentState
from app.agent.utils.nodes import (
    process_input,
    call_model,
    tools_condition,
    generate_response,
    tool_node,
)


graph = (
    StateGraph(AgentState)
    .add_node("process_input", process_input)
    .add_node("call_model", call_model)
    .add_node("tools", tool_node)
    .add_node("generate_response", generate_response)
    .add_edge(START, "process_input")
    .add_edge("process_input", "call_model")
    .add_conditional_edges("call_model", tools_condition, {"tools": "tools", "end": "generate_response"})
    .add_edge("tools", "call_model")
    .add_edge("generate_response", END)
    .compile(name="memomed_agent")
)

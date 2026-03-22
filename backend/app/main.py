import os
import asyncio
import traceback
from typing import Annotated, TypedDict, List, Union
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from pydantic import BaseModel
from pydantic_settings import BaseSettings

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END


# Pydantic settings class for environment variables
class Settings(BaseSettings):
    LLM_API_KEY: str
    LLM_BASE_URL: str
    LLM_MODEL: str
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

# Load settings
settings = Settings()
# print(f"Loaded settings from .env file")
# print(f"LLM_MODEL: {settings.LLM_MODEL}")
# print(f"LLM_BASE_URL: {settings.LLM_BASE_URL}")

app = FastAPI(title="Memomed API")

# Configure CORS for React development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define the state for our Agent
class AgentState(TypedDict):
    messages: List[BaseMessage]

# Define the graph logic
async def call_model(state: AgentState):
    messages = state["messages"]
    
    async def stream_handler(chunk):
        # This will be used for streaming
        pass
    
    llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            max_tokens=1000,
            streaming=True,
            extra_body={
                "enable_thinking": False  # 开启思考模式（False为关闭）
            }
        )
    response = await llm.ainvoke(messages)
    return {"messages": [response]}

# Build the LangGraph
workflow = StateGraph(AgentState)
workflow.add_node("agent", call_model)
workflow.set_entry_point("agent")
workflow.add_edge("agent", END)
agent_app = workflow.compile()

# Pydantic models for API
class ChatRequest(BaseModel):
    message: str
    history: List[dict] = []

class ChatResponse(BaseModel):
    reply: str


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        # Convert history and current message to LangChain messages
        messages = []
        for msg in request.history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            else:
                messages.append(AIMessage(content=msg["content"]))
        
        messages.append(HumanMessage(content=request.message))
        
        # Run the agent
        result = await agent_app.ainvoke({"messages": messages})
        
        last_message = result["messages"][-1]
        return ChatResponse(reply=last_message.content)
    except Exception as e:
        import traceback
        traceback.print_exc()  # 在终端打印详细错误堆栈
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    async def stream_generator():
        try:
            # Convert history and current message to LangChain messages
            messages = []
            for msg in request.history:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                else:
                    messages.append(AIMessage(content=msg["content"]))
            
            messages.append(HumanMessage(content=request.message))
            
            # Stream response through agent
            full_response = ""
            async for chunk in agent_app.astream(
                {"messages": messages},
                stream_mode="messages"
            ):
                # chunk is a tuple of (message, metadata)
                message, metadata = chunk
                if hasattr(message, "content") and message.content:
                    content = message.content
                    full_response += content
                    # Send chunk as SSE event
                    yield f"data: {content}\n\n"
                    await asyncio.sleep(0.01)  # Small delay to ensure smooth streaming
            
            # Send final event with complete response
            yield f"event: complete\ndata: {full_response}\n\n"
        except Exception as e:
            traceback.print_exc()
            yield f"event: error\ndata: {str(e)}\n\n"
    
    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)

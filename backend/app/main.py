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

from app.agent.api.routes import router as agent_router
from app.subjects.routes import router as subjects_router


# Pydantic settings class for environment variables
class Settings(BaseSettings):
    LLM_API_KEY: str
    LLM_BASE_URL: str
    LLM_MODEL: str
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"

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

app.include_router(agent_router)
app.include_router(subjects_router)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)

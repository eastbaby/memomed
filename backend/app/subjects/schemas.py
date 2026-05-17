from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


SubjectType = Literal["human", "pet"]
SubjectStatus = Literal["active", "archived"]
AliasSource = Literal["user", "ai", "system"]


class SubjectAliasResponse(BaseModel):
    id: str
    alias: str
    normalized_alias: str
    source: str
    status: str
    created_at: datetime


class SubjectResponse(BaseModel):
    id: str
    owner_user_id: str
    subject_type: SubjectType
    display_name: str
    legal_name: str | None
    relation_type: str | None
    species: str | None
    breed: str | None
    gender: str | None
    birth_date: date | None
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime
    aliases: list[SubjectAliasResponse] = Field(default_factory=list)


class SubjectCreateRequest(BaseModel):
    subject_type: SubjectType
    display_name: str = Field(min_length=1, max_length=100)
    alias: str | None = Field(default=None, max_length=100)
    legal_name: str | None = Field(default=None, max_length=100)
    relation_type: str | None = Field(default=None, max_length=30)
    species: str | None = Field(default=None, max_length=30)
    breed: str | None = Field(default=None, max_length=100)
    gender: str | None = Field(default=None, max_length=20)
    birth_date: date | None = None
    notes: str | None = None


class SubjectUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    legal_name: str | None = Field(default=None, max_length=100)
    relation_type: str | None = Field(default=None, max_length=30)
    species: str | None = Field(default=None, max_length=30)
    breed: str | None = Field(default=None, max_length=100)
    gender: str | None = Field(default=None, max_length=20)
    birth_date: date | None = None
    status: SubjectStatus | None = None
    notes: str | None = None


class AliasCreateRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=100)
    source: AliasSource = "user"


class AliasUpdateRequest(BaseModel):
    alias: str | None = Field(default=None, min_length=1, max_length=100)
    status: SubjectStatus | None = None

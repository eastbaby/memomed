from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.subjects.schemas import (
    AliasCreateRequest,
    AliasUpdateRequest,
    SubjectCreateRequest,
    SubjectResponse,
    SubjectUpdateRequest,
)
from app.subjects.service import (
    DuplicateAliasError,
    SubjectNotFoundError,
    create_alias,
    create_subject,
    list_subjects,
    update_alias,
    update_subject,
)


router = APIRouter(prefix="/api/subjects", tags=["subjects"])


@router.get("", response_model=list[SubjectResponse])
async def get_subjects() -> list[SubjectResponse]:
    return await list_subjects()


@router.post("", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
async def post_subject(payload: SubjectCreateRequest) -> SubjectResponse:
    try:
        return await create_subject(payload)
    except DuplicateAliasError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{subject_id}", response_model=SubjectResponse)
async def patch_subject(subject_id: UUID, payload: SubjectUpdateRequest) -> SubjectResponse:
    try:
        return await update_subject(subject_id, payload)
    except SubjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{subject_id}/aliases", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
async def post_alias(subject_id: UUID, payload: AliasCreateRequest) -> SubjectResponse:
    try:
        return await create_alias(subject_id, payload)
    except SubjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateAliasError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{subject_id}/aliases/{alias_id}", response_model=SubjectResponse)
async def patch_alias(subject_id: UUID, alias_id: UUID, payload: AliasUpdateRequest) -> SubjectResponse:
    try:
        return await update_alias(subject_id, alias_id, payload)
    except SubjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateAliasError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

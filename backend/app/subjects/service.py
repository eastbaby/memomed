import re
import unicodedata
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db import AsyncSessionLocal
from app.models.models import MmCareSubject, MmCareSubjectAlias
from app.subjects.schemas import (
    AliasCreateRequest,
    AliasUpdateRequest,
    SubjectAliasResponse,
    SubjectCreateRequest,
    SubjectResponse,
    SubjectUpdateRequest,
)


class SubjectNotFoundError(Exception):
    """Raised when a care subject or alias cannot be found for the owner."""


class DuplicateAliasError(Exception):
    """Raised when an alias conflicts with an existing active normalized alias."""


def normalize_alias(alias: str) -> str:
    normalized = unicodedata.normalize("NFKC", alias)
    normalized = re.sub(r"\s+", " ", normalized.strip())
    return normalized.casefold()


async def list_subjects(owner_user_id: str = "default") -> list[SubjectResponse]:
    async with AsyncSessionLocal() as session:
        statement = (
            select(MmCareSubject)
            .where(MmCareSubject.owner_user_id == owner_user_id)
            .order_by(MmCareSubject.status.asc(), MmCareSubject.subject_type.asc(), MmCareSubject.display_name.asc())
        )
        subjects = (await session.execute(statement)).scalars().all()
        aliases_by_subject = await _load_aliases_by_subject(session, [subject.id for subject in subjects])
        return [_subject_response(subject, aliases_by_subject.get(subject.id, [])) for subject in subjects]


async def create_subject(payload: SubjectCreateRequest, owner_user_id: str = "default") -> SubjectResponse:
    alias_text = _clean_text(payload.alias) or _clean_text(payload.display_name)
    if not alias_text:
        raise ValueError("主体名称不能为空。")

    async with AsyncSessionLocal() as session:
        subject = MmCareSubject(
            owner_user_id=owner_user_id,
            subject_type=payload.subject_type,
            display_name=_clean_text(payload.display_name),
            legal_name=_clean_text(payload.legal_name),
            relation_type=_clean_text(payload.relation_type),
            species=_clean_text(payload.species),
            breed=_clean_text(payload.breed),
            gender=_clean_text(payload.gender),
            birth_date=payload.birth_date,
            notes=_clean_text(payload.notes),
            status="active",
        )
        session.add(subject)
        await session.flush()

        alias = MmCareSubjectAlias(
            subject_id=subject.id,
            owner_user_id=owner_user_id,
            alias=alias_text,
            normalized_alias=normalize_alias(alias_text),
            source="user",
            status="active",
        )
        session.add(alias)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise DuplicateAliasError("该别名已经被其他成员或宠物使用。") from exc

    return await get_subject_response(subject.id, owner_user_id)


async def update_subject(
    subject_id: UUID,
    payload: SubjectUpdateRequest,
    owner_user_id: str = "default",
) -> SubjectResponse:
    async with AsyncSessionLocal() as session:
        subject = await _get_subject(session, subject_id, owner_user_id)
        updates = payload.model_dump(exclude_unset=True)
        for field_name, value in updates.items():
            setattr(subject, field_name, _clean_text(value) if isinstance(value, str) else value)
        if updates.get("status") == "archived":
            await _archive_aliases_for_subject(session, subject.id, owner_user_id)
        await session.commit()

    return await get_subject_response(subject_id, owner_user_id)


async def create_alias(
    subject_id: UUID,
    payload: AliasCreateRequest,
    owner_user_id: str = "default",
) -> SubjectResponse:
    async with AsyncSessionLocal() as session:
        subject = await _get_subject(session, subject_id, owner_user_id)
        alias_text = _clean_text(payload.alias)
        if not alias_text:
            raise ValueError("别名不能为空。")
        alias = MmCareSubjectAlias(
            subject_id=subject.id,
            owner_user_id=owner_user_id,
            alias=alias_text,
            normalized_alias=normalize_alias(alias_text),
            source=payload.source,
            status="active",
        )
        session.add(alias)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise DuplicateAliasError("该别名已经被其他成员或宠物使用。") from exc

    return await get_subject_response(subject_id, owner_user_id)


async def update_alias(
    subject_id: UUID,
    alias_id: UUID,
    payload: AliasUpdateRequest,
    owner_user_id: str = "default",
) -> SubjectResponse:
    async with AsyncSessionLocal() as session:
        await _get_subject(session, subject_id, owner_user_id)
        alias = await _get_alias(session, subject_id, alias_id, owner_user_id)
        updates = payload.model_dump(exclude_unset=True)
        if "alias" in updates:
            alias_text = _clean_text(updates["alias"])
            if not alias_text:
                raise ValueError("别名不能为空。")
            alias.alias = alias_text
            alias.normalized_alias = normalize_alias(alias_text)
        if "status" in updates:
            alias.status = updates["status"]
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise DuplicateAliasError("该别名已经被其他成员或宠物使用。") from exc

    return await get_subject_response(subject_id, owner_user_id)


async def get_subject_response(subject_id: UUID, owner_user_id: str = "default") -> SubjectResponse:
    async with AsyncSessionLocal() as session:
        subject = await _get_subject(session, subject_id, owner_user_id)
        aliases_by_subject = await _load_aliases_by_subject(session, [subject.id])
        return _subject_response(subject, aliases_by_subject.get(subject.id, []))


async def _get_subject(session, subject_id: UUID, owner_user_id: str) -> MmCareSubject:
    statement = select(MmCareSubject).where(
        MmCareSubject.id == subject_id,
        MmCareSubject.owner_user_id == owner_user_id,
    )
    subject = (await session.execute(statement)).scalar_one_or_none()
    if not subject:
        raise SubjectNotFoundError("没有找到这个家庭成员或宠物。")
    return subject


async def _get_alias(
    session,
    subject_id: UUID,
    alias_id: UUID,
    owner_user_id: str,
) -> MmCareSubjectAlias:
    statement = select(MmCareSubjectAlias).where(
        MmCareSubjectAlias.id == alias_id,
        MmCareSubjectAlias.subject_id == subject_id,
        MmCareSubjectAlias.owner_user_id == owner_user_id,
    )
    alias = (await session.execute(statement)).scalar_one_or_none()
    if not alias:
        raise SubjectNotFoundError("没有找到这个别名。")
    return alias


async def _load_aliases_by_subject(session, subject_ids: list[UUID]) -> dict[UUID, list[MmCareSubjectAlias]]:
    if not subject_ids:
        return {}
    statement = (
        select(MmCareSubjectAlias)
        .where(MmCareSubjectAlias.subject_id.in_(subject_ids))
        .order_by(MmCareSubjectAlias.status.asc(), MmCareSubjectAlias.alias.asc())
    )
    aliases = (await session.execute(statement)).scalars().all()
    grouped: dict[UUID, list[MmCareSubjectAlias]] = {}
    for alias in aliases:
        grouped.setdefault(alias.subject_id, []).append(alias)
    return grouped


async def _archive_aliases_for_subject(session, subject_id: UUID, owner_user_id: str) -> None:
    statement = (
        update(MmCareSubjectAlias)
        .where(MmCareSubjectAlias.subject_id == subject_id)
        .where(MmCareSubjectAlias.owner_user_id == owner_user_id)
        .where(MmCareSubjectAlias.status == "active")
        .values(status="archived")
    )
    await session.execute(statement)


def _subject_response(subject: MmCareSubject, aliases: list[MmCareSubjectAlias]) -> SubjectResponse:
    return SubjectResponse(
        id=str(subject.id),
        owner_user_id=subject.owner_user_id,
        subject_type=subject.subject_type,
        display_name=subject.display_name,
        legal_name=subject.legal_name,
        relation_type=subject.relation_type,
        species=subject.species,
        breed=subject.breed,
        gender=subject.gender,
        birth_date=subject.birth_date,
        status=subject.status,
        notes=subject.notes,
        created_at=subject.created_at,
        updated_at=subject.updated_at,
        aliases=[
            SubjectAliasResponse(
                id=str(alias.id),
                alias=alias.alias,
                normalized_alias=alias.normalized_alias,
                source=alias.source,
                status=alias.status,
                created_at=alias.created_at,
            )
            for alias in aliases
        ],
    )


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None

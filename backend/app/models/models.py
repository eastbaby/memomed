import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class Patient(Base):
    """家庭成员/被管理对象表。"""

    __tablename__ = "patients"
    __table_args__ = (
        Index("ix_patients_owner_user_id", "owner_user_id"),
        Index("ix_patients_patient_code", "patient_code"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)  # 家庭成员主键
    owner_user_id = Column(String(50), nullable=True)  # 应用拥有者标识，预留多用户能力
    patient_code = Column(String(50), nullable=False)  # 类别编码，如 self / mother / father / pet / other
    display_name = Column(String(100), nullable=False)  # 展示名称，如“妈妈”“爸爸”
    patient_name = Column(String(100), nullable=True)  # 真实姓名或宠物登记名，便于报告归属匹配
    patient_type = Column(String(20), nullable=False, server_default="human")  # 成员类型，如 human / pet
    gender = Column(String(20), nullable=True)  # 性别，可选
    birth_date = Column(Date, nullable=True)  # 出生日期，可选
    is_active = Column(Boolean, nullable=False, server_default="true")  # 是否仍处于活跃管理状态
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)  # 创建时间
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )  # 更新时间

    reports = relationship("MedicalReport", back_populates="patient")
    chunks = relationship("ReportChunk", back_populates="patient")


class MedicalReport(Base):
    """医疗报告主表。"""

    __tablename__ = "medical_reports"
    __table_args__ = (
        Index("ix_medical_reports_patient_id_report_date", "patient_id", "report_date"),
        Index("ix_medical_reports_patient_id_report_type", "patient_id", "report_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)  # 报告主键
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)  # 报告归属成员
    source_type = Column(String(30), nullable=True)  # 原始输入类型，如 image / pdf
    source_uri = Column(Text, nullable=True)  # 原始文件地址、对象存储 key 或临时 data URL
    report_date = Column(Date, nullable=False)  # 报告日期，重要检索字段
    report_type = Column(String(50), nullable=True)  # 报告类别，如血常规、CT、B超
    hospital_name = Column(String(255), nullable=True)  # 医院名称
    title = Column(String(255), nullable=True)  # 报告标题
    summary = Column(Text, nullable=True)  # 整份报告摘要
    ocr_pages = Column(JSONB, nullable=True)  # 按页保存 OCR 结果，如 [{"page_number": 1, "text": "..."}]
    parse_status = Column(String(30), nullable=False, server_default="pending")  # 解析状态，如 pending / parsed / failed
    parse_notes = Column(Text, nullable=True)  # 解析异常或待确认说明
    extra_metadata = Column("metadata", JSONB, nullable=True)  # 低频补充信息
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)  # 创建时间
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )  # 更新时间

    patient = relationship("Patient", back_populates="reports")
    chunks = relationship("ReportChunk", back_populates="report", cascade="all, delete-orphan")


class ReportChunk(Base):
    """报告切片向量表。"""

    __tablename__ = "report_chunks"
    __table_args__ = (
        Index("ix_report_chunks_patient_id_report_date", "patient_id", "report_date"),
        Index("ix_report_chunks_report_type", "report_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)  # 切片主键
    report_id = Column(UUID(as_uuid=True), ForeignKey("medical_reports.id", ondelete="CASCADE"), nullable=True)  # 所属报告主键
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)  # 冗余成员主键，便于直接过滤
    report_date = Column(Date, nullable=True)  # 冗余报告日期，便于按时间检索
    report_type = Column(String(50), nullable=True)  # 冗余报告类型，便于按类型过滤
    hospital_name = Column(String(255), nullable=True)  # 冗余医院名称
    content = Column(Text, nullable=False)  # 切片正文
    embedding = Column(Vector(1024), nullable=True)  # 文本向量，用 pgvector 做相似度检索
    page_number = Column(Integer, nullable=True)  # 来源页码
    chunk_index = Column(Integer, nullable=True)  # 在整份报告中的切片顺序编号
    chunk_metadata = Column("metadata", JSONB, nullable=True)  # 切片级补充信息，如 start_index
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)  # 创建时间
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )  # 更新时间

    report = relationship("MedicalReport", back_populates="chunks")
    patient = relationship("Patient", back_populates="chunks")


class MmCareSubject(Base):
    """Memomed V2 健康档案主体表，可表示家庭成员或宠物。"""

    __tablename__ = "mm_care_subjects"
    __table_args__ = (
        CheckConstraint("subject_type in ('human', 'pet')", name="ck_mm_care_subjects_subject_type"),
        CheckConstraint("status in ('active', 'archived')", name="ck_mm_care_subjects_status"),
        Index("idx_mm_care_subjects_owner_status", "owner_user_id", "status"),
        Index("idx_mm_care_subjects_type", "subject_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id = Column(String(64), nullable=False, server_default="default")
    subject_type = Column(String(20), nullable=False)
    display_name = Column(String(100), nullable=False)
    legal_name = Column(String(100), nullable=True)
    relation_type = Column(String(30), nullable=True)
    species = Column(String(30), nullable=True)
    breed = Column(String(100), nullable=True)
    gender = Column(String(20), nullable=True)
    birth_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, server_default="active")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    aliases = relationship(
        "MmCareSubjectAlias",
        back_populates="subject",
        cascade="all, delete-orphan",
    )


class MmCareSubjectAlias(Base):
    """Memomed V2 健康档案主体别名表。"""

    __tablename__ = "mm_care_subject_aliases"
    __table_args__ = (
        CheckConstraint("source in ('user', 'ai', 'system')", name="ck_mm_care_subject_aliases_source"),
        CheckConstraint("status in ('active', 'archived')", name="ck_mm_care_subject_aliases_status"),
        Index("idx_mm_care_subject_aliases_subject_id", "subject_id"),
        Index("idx_mm_care_subject_aliases_normalized_alias", "normalized_alias"),
        Index("uq_mm_care_subject_aliases_subject_alias", "subject_id", "normalized_alias", unique=True),
        Index(
            "uq_mm_care_subject_aliases_owner_active_alias",
            "owner_user_id",
            "normalized_alias",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mm_care_subjects.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id = Column(String(64), nullable=False, server_default="default")
    alias = Column(String(100), nullable=False)
    normalized_alias = Column(String(100), nullable=False)
    source = Column(String(20), nullable=False, server_default="user")
    status = Column(String(20), nullable=False, server_default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    subject = relationship("MmCareSubject", back_populates="aliases")


class MmAgentConversation(Base):
    """Memomed Agent 产品会话表。"""

    __tablename__ = "mm_agent_conversations"
    __table_args__ = (
        CheckConstraint("status in ('active', 'archived')", name="ck_mm_agent_conversations_status"),
        Index("idx_mm_agent_conversations_owner_status", "owner_user_id", "status"),
        Index("idx_mm_agent_conversations_updated_at", "updated_at"),
    )

    id = Column(String(100), primary_key=True)
    owner_user_id = Column(String(64), nullable=False, server_default="default")
    title = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, server_default="active")
    langgraph_thread_id = Column(String(100), nullable=False)
    last_event_seq = Column(BigInteger, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    archived_at = Column(DateTime(timezone=True), nullable=True)

    runs = relationship("MmAgentRun", back_populates="conversation", cascade="all, delete-orphan")
    events = relationship("MmAgentEvent", back_populates="conversation", cascade="all, delete-orphan")


class MmAgentRun(Base):
    """Memomed Agent 单次执行表。"""

    __tablename__ = "mm_agent_runs"
    __table_args__ = (
        CheckConstraint(
            "trigger_type in ('user_message', 'resume_interrupt', 'background_job')",
            name="ck_mm_agent_runs_trigger_type",
        ),
        CheckConstraint(
            "status in ('running', 'completed', 'interrupted', 'failed', 'cancelled')",
            name="ck_mm_agent_runs_status",
        ),
        Index("idx_mm_agent_runs_conversation_started", "conversation_id", "started_at"),
        Index("idx_mm_agent_runs_owner_status", "owner_user_id", "status"),
    )

    id = Column(String(100), primary_key=True)
    conversation_id = Column(
        String(100),
        ForeignKey("mm_agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id = Column(String(64), nullable=False, server_default="default")
    trigger_type = Column(String(30), nullable=False)
    status = Column(String(30), nullable=False, server_default="running")
    langgraph_run_id = Column(String(100), nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    run_metadata = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    conversation = relationship("MmAgentConversation", back_populates="runs")
    events = relationship("MmAgentEvent", back_populates="run")


class MmAgentEvent(Base):
    """Memomed Agent 产品时间线事件表。"""

    __tablename__ = "mm_agent_events"
    __table_args__ = (
        CheckConstraint(
            "role is null or role in ('user', 'assistant', 'tool', 'system')",
            name="ck_mm_agent_events_role",
        ),
        CheckConstraint(
            "visibility in ('visible', 'collapsed', 'debug', 'hidden')",
            name="ck_mm_agent_events_visibility",
        ),
        CheckConstraint(
            "status in ('pending', 'streaming', 'completed', 'failed')",
            name="ck_mm_agent_events_status",
        ),
        Index("idx_mm_agent_events_conversation_seq", "conversation_id", "seq", unique=True),
        Index("idx_mm_agent_events_turn_id", "turn_id"),
        Index("idx_mm_agent_events_work_item_id", "work_item_id"),
        Index("idx_mm_agent_events_run_id", "run_id"),
        Index("idx_mm_agent_events_owner_conversation", "owner_user_id", "conversation_id"),
        Index(
            "uq_mm_agent_events_run_dedupe_key",
            "run_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key is not null"),
        ),
    )

    id = Column(String(100), primary_key=True)
    conversation_id = Column(
        String(100),
        ForeignKey("mm_agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    turn_id = Column(String(100), nullable=True)
    run_id = Column(String(100), ForeignKey("mm_agent_runs.id", ondelete="SET NULL"), nullable=True)
    work_item_id = Column(String(100), nullable=True)
    work_item_type = Column(String(60), nullable=True)
    owner_user_id = Column(String(64), nullable=False, server_default="default")
    seq = Column(BigInteger, nullable=False)
    event_type = Column(String(40), nullable=False)
    role = Column(String(20), nullable=True)
    visibility = Column(String(20), nullable=False, server_default="visible")
    status = Column(String(20), nullable=False, server_default="completed")
    parent_event_id = Column(String(100), nullable=True)
    dedupe_key = Column(String(200), nullable=True)
    title = Column(String(200), nullable=True)
    content = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    conversation = relationship("MmAgentConversation", back_populates="events")
    run = relationship("MmAgentRun", back_populates="events")

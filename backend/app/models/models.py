import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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

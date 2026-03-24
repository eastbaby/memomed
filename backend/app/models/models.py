from sqlalchemy import Column, String, Text, Date, Integer, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from pgvector.sqlalchemy import Vector
import uuid

Base = declarative_base()


class MedicalReport(Base):
    """医疗报告主表"""
    __tablename__ = "medical_reports"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(String(50), nullable=False)  # 区分是爸爸还是妈妈
    report_date = Column(Date, nullable=False)  # 报告日期
    report_type = Column(String(50))  # 血检、CT、B超等
    hospital_name = Column(String(255))  # 医院名称
    file_path = Column(Text)  # 原始 PDF/图片路径
    summary = Column(Text)  # AI 自动生成的摘要
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 关联到报告切片
    chunks = relationship("ReportChunk", back_populates="report", cascade="all, delete-orphan")


class ReportChunk(Base):
    """报告切片向量表"""
    __tablename__ = "report_chunks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(UUID(as_uuid=True), ForeignKey("medical_reports.id", ondelete="CASCADE"), nullable=True)
    content = Column(Text, nullable=False)  # 切片文本内容
    embedding = Column(Vector(1024))  # 向量字段，使用pgvector的Vector类型，1024维(要和embedding模型的维度一致)
    page_number = Column(Integer)  # 来源页码
    index_in_report = Column(Integer)  # 切片在原报告中的顺序
    
    # 关联到医疗报告
    report = relationship("MedicalReport", back_populates="chunks")

import uuid
from datetime import datetime
from sqlalchemy import (Column, String, Integer, Boolean, Text, ForeignKey,
                         TIMESTAMP, Numeric, UniqueConstraint)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

    projects = relationship("ValidationProject", back_populates="user", cascade="all, delete-orphan")


class ValidationProject(Base):
    __tablename__ = "validation_projects"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

    user = relationship("User", back_populates="projects")
    runs = relationship("ValidationRun", back_populates="project", cascade="all, delete-orphan")


class ValidationRun(Base):
    __tablename__ = "validation_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_validation_runs_project_name"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("validation_projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(120), nullable=False)
    status = Column(String, default="draft")

    source_filename = Column(String)
    source_s3_key = Column(String)
    result_s3_key = Column(String)

    total_records = Column(Integer, default=0)
    valid_rows = Column(Integer, default=0)
    invalid_rows = Column(Integer, default=0)
    total_errors = Column(Integer, default=0)
    critical_errors = Column(Integer, default=0)
    health_score = Column(Numeric(5, 2), default=0)

    errors_by_type = Column(JSONB, default=list)
    errors_by_field = Column(JSONB, default=list)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    ran_at = Column(TIMESTAMP(timezone=True))
    completed_at = Column(TIMESTAMP(timezone=True))

    project = relationship("ValidationProject", back_populates="runs")
    fields = relationship("ValidationField", cascade="all, delete-orphan")
    exceptions = relationship("ValidationException", cascade="all, delete-orphan")


class ValidationField(Base):
    __tablename__ = "validation_fields"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("validation_runs.id", ondelete="CASCADE"))
    field_name = Column(String, nullable=False)
    column_index = Column(Integer, nullable=False)

    flag_key = Column(Boolean, default=False)
    flag_mandatory = Column(Boolean, default=False)
    flag_null = Column(Boolean, default=False)
    flag_email = Column(Boolean, default=False)
    flag_mobile = Column(Boolean, default=False)
    flag_date = Column(Boolean, default=False)
    flag_special_chars = Column(Boolean, default=False)

    case_format = Column(String)
    data_type = Column(String, default="string")
    max_length = Column(Integer)
    decimal_length = Column(Integer)

    regex = Column(Text)
    regex_prompt = Column(Text)


class ValidationException(Base):
    __tablename__ = "validation_exceptions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("validation_runs.id", ondelete="CASCADE"))
    row_number = Column(Integer, nullable=False)
    field_name = Column(String, nullable=False)
    actual_value = Column(Text)
    expected_value = Column(Text)
    error_type = Column(String, nullable=False)
    severity = Column(String, default="error")
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

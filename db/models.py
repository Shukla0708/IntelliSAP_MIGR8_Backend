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
    mappings = relationship("Mapping", cascade="all, delete-orphan")
    comparisons = relationship("ComparisonRun", back_populates="project", cascade="all, delete-orphan")


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

    processed_rows = Column(Integer, default=0)
    total_rows = Column(Integer, default=0)
    error_message = Column(Text)

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
    rule_source = Column(String, default="default")  # user | ai | default


class ValidationRuleTemplate(Base):
    """Curated SAP rule catalog. Embed name+aliases in memory; never sets flag_key."""
    __tablename__ = "validation_rule_templates"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    aliases = Column(Text, default="")

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
    regex_prompt = Column(Text)

    priority = Column(Integer, default=100)
    active = Column(Boolean, default=True)


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


class Mapping(Base):
    __tablename__ = "mappings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("validation_projects.id", ondelete="CASCADE"), nullable=False)
    mapping_name = Column(String, default="New field mapping run")
    status = Column(String, default="processing")  # processing | awaiting_approval | completed | failed
    number_range_type = Column(String)  # internal | external

    source_filename = Column(String)
    source_s3_key = Column(String)
    target_filename = Column(String)
    target_s3_key = Column(String)

    total_source_fields = Column(Integer, default=0)
    mapped_fields = Column(Integer, default=0)  # source fields that received >=1 candidate

    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    last_updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    temp_results = relationship("MappingTemp", cascade="all, delete-orphan")
    final_results = relationship("FinalMapping", cascade="all, delete-orphan")


class MappingTemp(Base):
    __tablename__ = "mapping_temp"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mapping_id = Column(UUID(as_uuid=True), ForeignKey("mappings.id", ondelete="CASCADE"))

    source_field = Column(String, nullable=False)
    key_field = Column(Boolean, default=False)
    # One entry per top-3 candidate: sap_table, sap_field, target_description,
    # embedding_score, datatype_match_score, confidence_score, reasoning.
    mapping = Column(JSONB, default=list)


class FinalMapping(Base):
    __tablename__ = "final_mapping"
    __table_args__ = (
        UniqueConstraint("mapping_id", "source_field", name="uq_final_mapping_mapping_source"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mapping_id = Column(UUID(as_uuid=True), ForeignKey("mappings.id", ondelete="CASCADE"))

    source_field = Column(String, nullable=False)
    target_field = Column(String, nullable=False)  # "{sap_table}.{sap_field}"
    # Carried over from mapping_temp.key_field on confirm. Several fields may be
    # flagged; together they form the composite business key used to join preload
    # and postload rows during comparison.
    key = Column(Boolean, default=False)


class ComparisonRun(Base):
    __tablename__ = "comparison_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_comparison_runs_project_name"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("validation_projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(120), nullable=False)
    status = Column(String, default="draft")  # draft | running | completed | failed

    mapping_id = Column(UUID(as_uuid=True), ForeignKey("mappings.id", ondelete="SET NULL"))
    business_key_columns_preload = Column(JSONB, default=list)
    business_key_columns_postload = Column(JSONB, default=list)

    preload_filename = Column(String)
    preload_s3_key = Column(String)
    postload_filename = Column(String)
    postload_s3_key = Column(String)
    result_s3_key = Column(String)

    total_preload_rows = Column(Integer, default=0)
    total_postload_rows = Column(Integer, default=0)
    matched_records = Column(Integer, default=0)
    different_count = Column(Integer, default=0)
    missing_count = Column(Integer, default=0)
    match_rate = Column(Numeric(5, 2), default=0)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    ran_at = Column(TIMESTAMP(timezone=True))
    completed_at = Column(TIMESTAMP(timezone=True))

    project = relationship("ValidationProject", back_populates="comparisons")
    discrepancies = relationship("ComparisonDiscrepancy", cascade="all, delete-orphan")


class ComparisonDiscrepancy(Base):
    __tablename__ = "comparison_discrepancies"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("comparison_runs.id", ondelete="CASCADE"))
    row_number = Column(Integer, nullable=False)
    business_key = Column(Text, nullable=False)
    field_name = Column(String, nullable=False)
    field_italic = Column(Boolean, nullable=False, default=False)
    preload_value = Column(Text)
    postload_value = Column(Text)
    difference_type = Column(String, nullable=False)
    severity = Column(String, default="warning")  # error | warning | info
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

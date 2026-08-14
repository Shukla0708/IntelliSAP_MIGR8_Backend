from datetime import datetime

from pydantic import BaseModel


class ReportErrorByType(BaseModel):
    label: str
    value: int


class ReportErrorByField(BaseModel):
    field: str
    count: int


class ReportRecentRun(BaseModel):
    id: str
    name: str
    status: str
    healthScore: float
    totalErrors: int
    totalRecords: int
    ranAt: datetime | None


class ReportValidationSection(BaseModel):
    totalRuns: int
    completedRuns: int
    failedRuns: int
    inProgressRuns: int
    totalRecords: int
    validRows: int
    invalidRows: int
    totalErrors: int
    criticalErrors: int
    avgHealthScore: float
    passRate: float
    errorsByType: list[ReportErrorByType]
    errorsByField: list[ReportErrorByField]
    recentRuns: list[ReportRecentRun]


class ReportReadiness(BaseModel):
    score: float
    validation: float
    comparison: float
    mapping: float


class ReportRecentComparisonRun(BaseModel):
    id: str
    name: str
    status: str
    mismatches: int
    records: str
    ranAt: datetime | None


class ReportComparisonSection(BaseModel):
    totalRuns: int
    completedRuns: int
    totalMismatches: int
    avgMatchRate: float
    matchedRecords: int
    differentCount: int
    missingCount: int
    recentRuns: list[ReportRecentComparisonRun]


class ReportRecentMappingRun(BaseModel):
    id: str
    name: str
    status: str
    unmapped: int
    fields: str
    ranAt: datetime | None


class ReportMappingSection(BaseModel):
    totalRuns: int
    completedRuns: int
    totalFields: int
    unmappedFields: int
    approvalRate: float
    avgConfidence: float
    recentRuns: list[ReportRecentMappingRun]


class ReportProject(BaseModel):
    id: str
    name: str
    created_at: datetime


class ProjectReportOut(BaseModel):
    project: ReportProject
    generatedAt: datetime
    readiness: ReportReadiness
    validation: ReportValidationSection
    comparison: ReportComparisonSection
    mapping: ReportMappingSection

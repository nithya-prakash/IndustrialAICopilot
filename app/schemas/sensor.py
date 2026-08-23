import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SensorSnapshotRequest(BaseModel):
    equipment_id: str = Field(min_length=1, max_length=128)
    equipment_type: str | None = None
    readings: dict[str, float] = Field(min_length=1)
    recorded_at: datetime | None = None


class SensorReadingResponse(BaseModel):
    id: uuid.UUID
    equipment_id: str
    metric: str
    value: float
    unit: str | None
    recorded_at: datetime


class SensorHistoryResponse(BaseModel):
    equipment_id: str
    metric: str
    readings: list[SensorReadingResponse]


class TrendResponse(BaseModel):
    direction: str
    slope_per_hour: float
    r_squared: float


class AnomalyResponse(BaseModel):
    recorded_at: datetime
    value: float
    score: float
    method: str


class StatisticalSummaryResponse(BaseModel):
    count: int
    mean: float
    median: float
    std_dev: float
    min_value: float
    max_value: float


class ThresholdViolationResponse(BaseModel):
    recorded_at: datetime
    value: float
    limit_min: float | None
    limit_max: float | None
    source: str | None


class SensorAnalysisResponse(BaseModel):
    equipment_id: str
    metric: str
    unit: str | None
    reading_count: int
    summary: StatisticalSummaryResponse | None
    trend: TrendResponse | None
    anomalies: list[AnomalyResponse]
    threshold_violations: list[ThresholdViolationResponse]
    baseline_comparison: dict | None

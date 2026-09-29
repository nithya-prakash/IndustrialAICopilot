"""Shared size limits for client-supplied fields.

Two reasons for these, not one: text that reaches an LLM/VLM prompt is
billed per token, so an unbounded `question` lets a single request run up
cost; and equipment IDs/types and sensor metric names land in fixed-width
DB columns (String(128) / String(64)), where an oversized value used to
surface as a Postgres error (500) instead of a clean 422.
"""
from typing import Annotated

from pydantic import Field, StringConstraints

QUESTION_MAX_CHARS = 2000
EQUIPMENT_FIELD_MAX_CHARS = 128  # matches the String(128) columns
SENSOR_METRIC_MAX_CHARS = 64  # matches SensorReading.metric String(64)
MAX_SENSOR_READINGS = 50

Question = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=QUESTION_MAX_CHARS)
]
EquipmentField = Annotated[
    str, StringConstraints(min_length=1, max_length=EQUIPMENT_FIELD_MAX_CHARS)
]
SensorMetric = Annotated[str, StringConstraints(min_length=1, max_length=SENSOR_METRIC_MAX_CHARS)]
# NaN/inf would poison every downstream statistic (mean, z-score, trend).
SensorValue = Annotated[float, Field(allow_inf_nan=False)]
SensorReadings = Annotated[
    dict[SensorMetric, SensorValue], Field(min_length=1, max_length=MAX_SENSOR_READINGS)
]

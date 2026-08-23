from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.sensors import (
    SensorPoint,
    check_thresholds,
    compare_to_baseline,
    detect_anomalies_isolation_forest,
    detect_anomalies_statistical,
    detect_trend,
    statistical_summary,
)
from app.core.deps import get_current_user
from app.database import get_db
from app.models.sensor import SensorReading
from app.models.user import User
from app.schemas.sensor import (
    AnomalyResponse,
    SensorAnalysisResponse,
    SensorHistoryResponse,
    SensorReadingResponse,
    SensorSnapshotRequest,
    StatisticalSummaryResponse,
    ThresholdViolationResponse,
    TrendResponse,
)
from app.services.sensor_service import (
    ILLUSTRATIVE_THRESHOLDS,
    InvalidSensorDataError,
    ingest_snapshot,
    query_sensor_history,
)

router = APIRouter(prefix="/api/v1/sensors", tags=["sensors"])


def _to_reading_response(reading: SensorReading) -> SensorReadingResponse:
    return SensorReadingResponse(
        id=reading.id,
        equipment_id=reading.equipment_id,
        metric=reading.metric,
        value=reading.value,
        unit=reading.unit,
        recorded_at=reading.recorded_at,
    )


@router.post("/upload", response_model=SensorHistoryResponse, status_code=status.HTTP_201_CREATED)
async def upload(
    payload: SensorSnapshotRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SensorHistoryResponse:
    try:
        rows = await ingest_snapshot(
            db,
            owner_id=user.id,
            tenant_id=user.tenant_id,
            equipment_id=payload.equipment_id,
            equipment_type=payload.equipment_type,
            readings=payload.readings,
            recorded_at=payload.recorded_at or datetime.now(),
        )
    except InvalidSensorDataError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return SensorHistoryResponse(
        equipment_id=payload.equipment_id,
        metric="(multiple)",
        readings=[_to_reading_response(r) for r in rows],
    )


@router.get("/{equipment_id}/history", response_model=SensorHistoryResponse)
async def history(
    equipment_id: str,
    metric: str = Query(...),
    start_time: datetime = Query(...),
    end_time: datetime = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SensorHistoryResponse:
    readings = await query_sensor_history(
        db,
        tenant_id=user.tenant_id,
        equipment_id=equipment_id,
        metric=metric,
        start_time=start_time,
        end_time=end_time,
    )
    return SensorHistoryResponse(
        equipment_id=equipment_id,
        metric=metric,
        readings=[_to_reading_response(r) for r in readings],
    )


@router.get("/{equipment_id}/analysis", response_model=SensorAnalysisResponse)
async def analysis(
    equipment_id: str,
    metric: str = Query(...),
    start_time: datetime = Query(...),
    end_time: datetime = Query(...),
    anomaly_method: str = Query(default="statistical", pattern="^(statistical|isolation_forest)$"),
    baseline_days: int = Query(default=30, ge=0, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SensorAnalysisResponse:
    readings = await query_sensor_history(
        db,
        tenant_id=user.tenant_id,
        equipment_id=equipment_id,
        metric=metric,
        start_time=start_time,
        end_time=end_time,
    )
    points = [SensorPoint(recorded_at=r.recorded_at, value=r.value) for r in readings]
    unit = readings[0].unit if readings else None

    summary = statistical_summary(points)
    trend = detect_trend(points)

    if anomaly_method == "isolation_forest":
        anomalies = detect_anomalies_isolation_forest(points)
    else:
        anomalies = detect_anomalies_statistical(points)

    threshold = ILLUSTRATIVE_THRESHOLDS.get(metric)
    violations = []
    if threshold:
        for p in check_thresholds(points, threshold.get("min"), threshold.get("max")):
            violations.append(
                ThresholdViolationResponse(
                    recorded_at=p.recorded_at,
                    value=p.value,
                    limit_min=threshold.get("min"),
                    limit_max=threshold.get("max"),
                    source=threshold.get("source"),
                )
            )

    baseline_comparison = None
    if points and baseline_days > 0:
        baseline_start = start_time - timedelta(days=baseline_days)
        baseline_readings = await query_sensor_history(
            db,
            tenant_id=user.tenant_id,
            equipment_id=equipment_id,
            metric=metric,
            start_time=baseline_start,
            end_time=start_time,
        )
        baseline_points = [
            SensorPoint(recorded_at=r.recorded_at, value=r.value) for r in baseline_readings
        ]
        latest = max(points, key=lambda p: p.recorded_at)
        baseline_comparison = compare_to_baseline(latest.value, baseline_points)

    return SensorAnalysisResponse(
        equipment_id=equipment_id,
        metric=metric,
        unit=unit,
        reading_count=len(points),
        summary=StatisticalSummaryResponse(**summary.__dict__) if summary else None,
        trend=TrendResponse(**trend.__dict__) if trend else None,
        anomalies=[AnomalyResponse(**a.__dict__) for a in anomalies],
        threshold_violations=violations,
        baseline_comparison=baseline_comparison,
    )

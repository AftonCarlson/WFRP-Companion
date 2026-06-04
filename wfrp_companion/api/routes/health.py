from __future__ import annotations

from fastapi import APIRouter

from wfrp_companion.api.dependencies import ConfigDependency
from wfrp_companion.api.schemas import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(config: ConfigDependency) -> HealthResponse:
    return HealthResponse(status="ok", database="configured")

"""Consultation module package."""

from app.modules.consultation.repository import ConsultationRepository
from app.modules.consultation.router import router as consultation_router
from app.modules.consultation.service import ConsultationService

__all__ = [
    "ConsultationRepository",
    "ConsultationService",
    "consultation_router",
]

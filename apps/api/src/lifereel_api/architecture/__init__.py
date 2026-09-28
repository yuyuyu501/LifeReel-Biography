"""Service boundaries shared by the modular monolith and future services."""

from lifereel_api.architecture.events import EventEnvelope, event_type_for_job
from lifereel_api.architecture.services import SERVICE_CATALOG, ServiceName

__all__ = ["EventEnvelope", "SERVICE_CATALOG", "ServiceName", "event_type_for_job"]

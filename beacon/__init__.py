"""Beacon v2.1 Backend Signal Processing, Feature Extraction & Serving Package."""

from .features import extract_spatial_features
from .incidents import Incident, IncidentManager, IncidentState
from .location_model import LocationClassifier
from .signal import BeepEvent, SignalProcessor, compute_purity

__all__ = [
    "SignalProcessor",
    "compute_purity",
    "extract_spatial_features",
    "BeepEvent",
    "LocationClassifier",
    "Incident",
    "IncidentManager",
    "IncidentState",
]

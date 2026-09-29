"""Compatibility import for provider contracts now owned by model-gateway."""
import sys

from lifereel_api.providers import video

sys.modules[__name__] = video

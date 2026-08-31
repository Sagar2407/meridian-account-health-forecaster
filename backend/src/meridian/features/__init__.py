"""Deterministic feature computation at an arbitrary point-in-time cutoff.

The Quantitative Analyst is deterministic code. An LLM may later interpret these
numbers, but it must never calculate them (plan section 10).
"""

from meridian.features.builder import AccountFeatures, FeatureCoverage, build_features
from meridian.features.spec import FEATURE_SPECS, MODEL_INPUT_FEATURES, FeatureSpec

__all__ = [
    "FEATURE_SPECS",
    "MODEL_INPUT_FEATURES",
    "AccountFeatures",
    "FeatureCoverage",
    "FeatureSpec",
    "build_features",
]

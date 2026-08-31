"""Provider-neutral structured generation (ADR 0004).

Graph and tool code imports from here. Only `openai_compatible` may import a
vendor SDK, and `test_import_boundary.py` fails the build if that changes.
"""

from meridian.llm.base import (
    GenerationError,
    GenerationRequest,
    ProviderNotConfiguredError,
    StructuredGenerator,
    StructuredOutputError,
    StructuredResult,
    Usage,
    generate_structured,
)
from meridian.llm.fake import EchoGenerator, ScriptedGenerator
from meridian.llm.providers import ProviderStatus, build_generator, describe_provider

__all__ = [
    "EchoGenerator",
    "GenerationError",
    "GenerationRequest",
    "ProviderNotConfiguredError",
    "ProviderStatus",
    "ScriptedGenerator",
    "StructuredGenerator",
    "StructuredOutputError",
    "StructuredResult",
    "Usage",
    "build_generator",
    "describe_provider",
    "generate_structured",
]

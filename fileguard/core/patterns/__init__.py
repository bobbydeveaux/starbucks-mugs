"""PII pattern library for FileGuard.

Provides the built-in UK PII pattern set and custom pattern loading.
"""

from fileguard.core.patterns.uk_patterns import (
    BUILTIN_PATTERNS,
    PatternDefinition,
    get_patterns,
    load_custom_patterns,
)

__all__ = [
    "BUILTIN_PATTERNS",
    "PatternDefinition",
    "get_patterns",
    "load_custom_patterns",
]

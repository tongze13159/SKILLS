"""External-service boundaries. Network adapters are explicit stubs in v1."""

from .base import adapter_stub
from .mock_adapter import MockAdapter

__all__ = ["MockAdapter", "adapter_stub"]

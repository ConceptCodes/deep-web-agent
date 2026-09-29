"""Backend construction for agent files, skills, and long-term memory."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents import FilesystemPermission
from deepagents.backends import CompositeBackend, StateBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import BackendProtocol

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class BackendSetup:
    backend: BackendProtocol
    permissions: list[FilesystemPermission]
    store: Any = None


def initialize_backend(
    memory_backend: BackendProtocol,
    store: Any = None,
) -> BackendSetup:
    """Build the agent filesystem, keeping scratch data separate from disk files."""
    backend = CompositeBackend(
        default=StateBackend(),
        routes={
            "/skills/": FilesystemBackend(
                root_dir=str(PROJECT_ROOT / "skills"),
                virtual_mode=True,
            ),
            "/memories/": memory_backend,
        },
    )
    permissions = [
        FilesystemPermission(
            operations=["write"],
            paths=["/memories/insights.md"],
            mode="allow",
        ),
        FilesystemPermission(
            operations=["write"],
            paths=["/memories/**"],
            mode="deny",
        ),
        FilesystemPermission(
            operations=["write"],
            paths=["/skills/**"],
            mode="deny",
        ),
    ]
    return BackendSetup(backend=backend, permissions=permissions, store=store)

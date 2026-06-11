"""Mocked network layer for the P1-D boundary tests (spec v0.3 §12 P1-D:
"asserting canaries never reach a mocked network layer or log capture").

NetworkSentry swaps the stdlib socket constructors for guards that record
the attempt and raise. Test scaffolding only — product code must never
import this module. Swapping stdlib entry points is exactly what the spec
mandates here: a runtime fixture proving no code path can open an outbound
channel, whatever library sits on top of it."""

from __future__ import annotations

import socket


class BoundaryViolation(Exception):
    """Something attempted an outbound network operation under the sentry."""


class NetworkSentry:
    """Context manager: blocks and records every socket-level attempt."""

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self._originals: dict[str, object] = {}

    def __enter__(self) -> "NetworkSentry":
        self._originals = {
            "socket": socket.socket,
            "create_connection": socket.create_connection,
            "getaddrinfo": socket.getaddrinfo,
        }
        socket.socket = self._guard("socket")  # type: ignore[misc]
        socket.create_connection = self._guard("create_connection")  # type: ignore[assignment]
        socket.getaddrinfo = self._guard("getaddrinfo")  # type: ignore[assignment]
        return self

    def __exit__(self, *exc_info: object) -> None:
        socket.socket = self._originals["socket"]  # type: ignore[misc]
        socket.create_connection = self._originals["create_connection"]  # type: ignore[assignment]
        socket.getaddrinfo = self._originals["getaddrinfo"]  # type: ignore[assignment]

    def _guard(self, name: str):
        def blocked(*args: object, **kwargs: object):
            self.attempts.append(f"{name}{args!r}")
            raise BoundaryViolation(
                f"outbound network blocked by boundary sentry: {name}{args!r}"
            )

        return blocked

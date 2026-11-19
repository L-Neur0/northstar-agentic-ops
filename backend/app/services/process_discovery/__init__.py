"""The discovery engine facade: the only import surface for the routes and the app lifespan (spec 10 §3.9, spec 12 §2, spec 15 §2).

It re-exports the service use cases, their errors and the composition helpers from `service.py`
(`DiscoveryService`, `build_context`, `build_graph`, `create_llm`, the LLM and store errors the
routes map to HTTP codes). Import order matters: `app.core.config` and the models import `domain`
modules, and `service.py` imports the models, so the service is loaded lazily on first attribute
access, never when the package is imported (AC-12.44); the names below are imported for type
checkers only.
"""

from __future__ import annotations

import importlib
import importlib.util
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .service import (
        ConflictError as ConflictError,
    )
    from .service import (
        DiscoveryService as DiscoveryService,
    )
    from .service import (
        IdeaAlreadyStarted as IdeaAlreadyStarted,
    )
    from .service import (
        LLMBudgetExceededError as LLMBudgetExceededError,
    )
    from .service import (
        LLMConfigError as LLMConfigError,
    )
    from .service import (
        MapIncomplete as MapIncomplete,
    )
    from .service import (
        NotFound as NotFound,
    )
    from .service import (
        SessionClosed as SessionClosed,
    )
    from .service import (
        UnknownCluster as UnknownCluster,
    )
    from .service import (
        UnsafeInput as UnsafeInput,
    )
    from .service import (
        build_context as build_context,
    )
    from .service import (
        build_graph as build_graph,
    )
    from .service import (
        create_llm as create_llm,
    )

_SERVICE = f"{__name__}.service"


def __getattr__(name: str) -> Any:
    """Load `service.py` on first use and return its attribute `name`."""
    if name.startswith("__"):
        raise AttributeError(name)
    # `from app.services.process_discovery import domain` asks for the attribute before importing
    # the subpackage; answer with the subpackage itself so it never drags the service in.
    if importlib.util.find_spec(f"{__name__}.{name}") is not None:
        return importlib.import_module(f"{__name__}.{name}")
    try:
        service = importlib.import_module(_SERVICE)
    except ModuleNotFoundError as exc:
        if exc.name != _SERVICE:
            raise
        raise AttributeError(f"module {__name__!r} has no attribute {name!r} (no service yet)") from exc
    try:
        return getattr(service, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

"""Re-exports of the taxonomy and wording models for the config loader (spec 10 §3.6, spec 12 §3.8, §3.10).

Why: the loader in `app.core.config` validates every company file, but the taxonomy and wording
models belong to the field registry (spec 12), because their rules (unique keywords, known field
IDs) are registry rules. Keeping this module as the loader's import point means the loader never
changes when those models do.
What: re-exports `Taxonomy` from `domain.taxonomy` and `WordingOverrides` from `domain.field_spec`.
Must not define models of its own or add rules; a rule belongs in the domain module that owns it.
"""

from __future__ import annotations

from app.services.process_discovery.domain.field_spec import WordingOverrides
from app.services.process_discovery.domain.taxonomy import Taxonomy

__all__ = ["Taxonomy", "WordingOverrides"]

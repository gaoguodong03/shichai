"""Strict API request model base.

API request bodies follow docs/development/coding-standard.md: unknown top-level
fields are rejected at the Pydantic boundary instead of being ignored or used as
legacy compatibility controls.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

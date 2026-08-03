"""Typed, versioned rule models for deterministic triage."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class RuleBase(BaseModel):
    """Common fields for triage rules."""

    id: str
    description: str
    severity: Literal["warning", "error"]


class TableNonEmptyRule(RuleBase):
    """Require that a table has at least one row."""

    type: Literal["table_non_empty"] = "table_non_empty"
    table_name: str


class RequiredColumnsRule(RuleBase):
    """Require specific columns to have no null/invalid values."""

    type: Literal["required_columns_present"] = "required_columns_present"
    table_name: str
    columns: list[str]


class ForeignKeyIntegrityRule(RuleBase):
    """Require zero FK orphans for a relation."""

    type: Literal["foreign_key_integrity"] = "foreign_key_integrity"
    child_table: str
    parent_table: str
    relation_name: str


class CrossTableMinimumRule(RuleBase):
    """Require dependent/driving table minimum ratio."""

    type: Literal["cross_table_minimum"] = "cross_table_minimum"
    driving_table: str
    dependent_table: str
    minimum_ratio: float


TriageRule = Annotated[
    TableNonEmptyRule | RequiredColumnsRule | ForeignKeyIntegrityRule | CrossTableMinimumRule,
    Field(discriminator="type"),
]


class RuleSet(BaseModel):
    """Versioned collection of triage rules."""

    name: str
    version: str
    rules: list[TriageRule]

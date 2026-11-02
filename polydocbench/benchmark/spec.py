"""Explicit research targets, separate from runnable generation settings."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BenchmarkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1"] = "0.1"
    benchmark_id: str = Field(min_length=1)
    status: Literal["draft"] = "draft"
    languages: list[str] = Field(min_length=1)
    articles_per_language: int = Field(gt=0)
    templates: list[str] = Field(min_length=1)
    pages_per_document: int = Field(gt=0)
    page_selection: Literal["stratified_content"] = "stratified_content"
    conditions: list[Literal["clean", "light_scan", "medium_scan", "heavy_scan"]] = Field(min_length=1)
    variants_per_noisy_condition: int = Field(gt=0)
    master_seed: int = Field(ge=0)
    split_unit: Literal["source_family"] = "source_family"
    development_fraction: float = Field(gt=0, lt=1)
    tasks: list[Literal["quality", "ordering", "structure"]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_axes(self) -> "BenchmarkSpec":
        for name in ("languages", "templates", "conditions", "tasks"):
            values = getattr(self, name)
            if any(not value.strip() for value in values) or len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique, nonempty values")
        if "clean" not in self.conditions:
            raise ValueError("A clean control condition is required")
        return self

    def target_counts(self) -> dict[str, int]:
        sources = len(self.languages) * self.articles_per_language
        documents = sources * len(self.templates)
        pages = documents * self.pages_per_document
        variants = int("clean" in self.conditions) + (
            len(self.conditions) - int("clean" in self.conditions)
        ) * self.variants_per_noisy_condition
        return {"source_documents": sources, "rendered_documents": documents,
                "base_pages": pages, "images": pages * variants}


def load_benchmark_spec(path: str | Path) -> BenchmarkSpec:
    return BenchmarkSpec.model_validate_json(Path(path).read_text(encoding="utf-8"))

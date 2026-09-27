from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LlmMediaDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blob_ref: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    byte_size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    application_ref: str | None = Field(
        default=None,
        pattern=r"^(tool_attachment|user_attachment):[A-Za-z0-9._:-]+$",
    )


class LlmMaterializedMediaDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mime_type: str = Field(min_length=1)
    byte_size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width_px: int | None = Field(default=None, gt=0)
    height_px: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_dimensions(self) -> LlmMaterializedMediaDescriptor:
        if (self.width_px is None) != (self.height_px is None):
            raise ValueError("materialized media dimensions must be provided together")
        return self


class LlmImageProjectionRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["webp_resize"]
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    quality: Literal[80]
    method: Literal[6]
    encoder: str = Field(min_length=1)


class LlmMediaProjection(BaseModel):
    """Provider-neutral record of the exact media representation sent upstream."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["inline", "reference"]
    source: LlmMediaDescriptor
    materialized: LlmMaterializedMediaDescriptor | None = None
    image_recipe: LlmImageProjectionRecipe | None = None

    @model_validator(mode="after")
    def validate_state(self) -> LlmMediaProjection:
        # A document reaches the model as text, so every media input is an image
        # (#1404). Both states say so, and the adapters read it as given.
        if not self.source.mime_type.startswith("image/"):
            raise ValueError("media projection requires image media")
        if self.state == "reference":
            if self.source.application_ref is None:
                raise ValueError("reference projection requires an application_ref")
            if self.materialized is not None or self.image_recipe is not None:
                raise ValueError("reference projection must not contain inline media")
            return self
        if self.materialized is None:
            raise ValueError("inline projection requires materialized media metadata")
        if self.materialized.width_px is None:
            raise ValueError("inline image projection requires materialized dimensions")
        if self.image_recipe is not None:
            if self.materialized.mime_type != "image/webp":
                raise ValueError("image projection materialization must be WebP")
            if (
                self.materialized.width_px != self.image_recipe.width_px
                or self.materialized.height_px != self.image_recipe.height_px
            ):
                raise ValueError(
                    "image recipe dimensions must match materialized media"
                )
        return self


__all__ = [
    "LlmImageProjectionRecipe",
    "LlmMaterializedMediaDescriptor",
    "LlmMediaDescriptor",
    "LlmMediaProjection",
]

import json
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lifereel_api.modules.interview.profile_template import FIELD_MAP


class EntryChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: UUID | None = None
    field_key: str
    record_key: str = Field(default="single", min_length=1, max_length=100)
    value: str | dict | list = ""
    state: Literal["empty", "filled", "unknown", "deferred", "declined", "not_applicable"] = (
        "filled"
    )
    certainty: Literal["reported", "confirmed", "uncertain", "disputed", "pending"] = "reported"
    use_scope: Literal["works", "internal", "pseudonym"] = "works"
    delete: bool = False
    pseudonyms: dict[str, str] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def valid_field(self):
        if self.field_key not in FIELD_MAP:
            raise ValueError("unknown_profile_field")
        if len(json.dumps(self.value, ensure_ascii=False)) > 12000:
            raise ValueError("profile_value_too_large")
        if not self.field_key.endswith("[]") and self.record_key != "single":
            raise ValueError("single_field_requires_single_record")
        if self.state == "filled" and not self.value and not self.delete:
            raise ValueError("filled_field_requires_content")
        if any(
            not k.strip() or not v.strip() or len(k) > 100 or len(v) > 100
            for k, v in self.pseudonyms.items()
        ):
            raise ValueError("invalid_pseudonyms")
        if (
            self.use_scope == "pseudonym"
            and self.state == "filled"
            and not self.pseudonyms
            and not self.delete
        ):
            raise ValueError("pseudonym_mapping_required")
        return self


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0, strict=True)
    request_id: UUID = Field(default_factory=uuid4)
    changes: list[EntryChange] = Field(max_length=80)

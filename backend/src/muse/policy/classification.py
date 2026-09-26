"""Classification vocabulary. Values are assigned by the trusted registry, never by the model."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class RiskClass(StrEnum):
    READ_ONLY = "READ_ONLY"
    LOCAL_MUTATION = "LOCAL_MUTATION"
    EXTERNAL_WRITE = "EXTERNAL_WRITE"
    SENSITIVE_EXTERNAL_WRITE = "SENSITIVE_EXTERNAL_WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"


class SideEffectClass(StrEnum):
    NONE = "NONE"
    LOCAL_FILE_WRITE = "LOCAL_FILE_WRITE"
    NETWORK_READ = "NETWORK_READ"
    NETWORK_WRITE = "NETWORK_WRITE"
    MESSAGE_SEND = "MESSAGE_SEND"
    REMOTE_UPDATE = "REMOTE_UPDATE"
    PURCHASE = "PURCHASE"
    DELETE = "DELETE"


class DataClassification(StrEnum):
    PUBLIC = "PUBLIC"
    PERSONAL = "PERSONAL"
    AUTHENTICATED = "AUTHENTICATED"
    SECRET = "SECRET"


class Classification(BaseModel):
    model_config = ConfigDict(frozen=True)

    risk: RiskClass
    side_effect: SideEffectClass
    required_permissions: tuple[str, ...] = ()
    data_classification: DataClassification
    destination: str | None = None

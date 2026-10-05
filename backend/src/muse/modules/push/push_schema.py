"""Shapes for web push: browser subscriptions and the server's public key."""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from muse.modules.notifications.budget import Feedback, Level


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class Subscribe(BaseModel):
    """The browser's PushSubscription.toJSON(), as is."""

    model_config = ConfigDict(extra="ignore")

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: SubscriptionKeys


class Unsubscribe(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)


class SubscriptionView(BaseModel):
    id: uuid.UUID
    user_agent: str | None
    last_success_at: dt.datetime | None
    created_at: dt.datetime


class PublicKey(BaseModel):
    public_key: str  # base64url, uncompressed P-256 point: the applicationServerKey


class FeedbackRequest(BaseModel):
    signal: Feedback


class PreferenceUpdate(BaseModel):
    level: Level
    daily_cap: int = Field(ge=0, le=50)

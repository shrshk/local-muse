"""SQLAlchemy Core tables. Every migration that changes shape updates this file too."""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

service_heartbeats = Table(
    "service_heartbeats",
    metadata,
    Column("service", Text, primary_key=True),
    Column("status", Text, nullable=False),
    Column("detail", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("username", Text, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

conversations = Table(
    "conversations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("title", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_conversations_user_updated", "user_id", "updated_at"),
)

messages = Table(
    "messages",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column(
        "conversation_id",
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("role", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_seq"),
)

actions = Table(
    "actions",
    metadata,
    Column("action_id", UUID(as_uuid=True), primary_key=True),
    Column("approval_key", Text, nullable=False),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("conversation_id", UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False),
    Column("topic_id", UUID(as_uuid=True)),
    Column("actor_id", Text, nullable=False),
    Column("tool", Text, nullable=False),
    Column("proposal", JSONB, nullable=False),
    Column("decision", Text, nullable=False),
    Column("decision_reason", Text),
    Column("status", Text, nullable=False),
    Column("result", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("executed_at", DateTime(timezone=True)),
    Index("ix_actions_conversation_created", "conversation_id", "created_at"),
    Index("ix_actions_approval_key", "approval_key"),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("event_type", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("user_id", UUID(as_uuid=True)),
    Column("conversation_id", UUID(as_uuid=True)),
    Column("action_id", UUID(as_uuid=True)),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_audit_events_action", "action_id"),
    Index("ix_audit_events_created", "created_at"),
)

realtime_channel_seqs = Table(
    "realtime_channel_seqs",
    metadata,
    Column("channel", Text, primary_key=True),
    Column("seq", BigInteger, nullable=False),
)

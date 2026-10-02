"""SQLAlchemy Core tables. Every migration that changes shape updates this file too."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID

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

topics = Table(
    "topics",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column(
        "conversation_id",
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("title", Text, nullable=False),
    Column("objective", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("workflow_id", Text),
    Column("result", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    Index("ix_topics_conversation_status", "conversation_id", "status"),
)

topic_memory = Table(
    "topic_memory",
    metadata,
    Column(
        "topic_id",
        UUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("document", JSONB, nullable=False),
    Column("version", Integer, nullable=False, server_default=text("1")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

profile_memory = Table(
    "profile_memory",
    metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("key", Text, nullable=False),
    Column("value", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("user_id", "key", name="pk_profile_memory"),
)

conversation_summaries = Table(
    "conversation_summaries",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column(
        "conversation_id",
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("up_to_seq", Integer, nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("conversation_id", "up_to_seq", name="uq_conversation_summaries_seq"),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column(
        "conversation_id",
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("topic_id", UUID(as_uuid=True)),
    Column("kind", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("classification", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_artifacts_conversation", "conversation_id"),
)

sandboxes = Table(
    "sandboxes",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("conversation_id", UUID(as_uuid=True), nullable=False),
    Column("topic_id", UUID(as_uuid=True)),
    Column("volume_name", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

approvals = Table(
    "approvals",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("action_id", UUID(as_uuid=True), ForeignKey("actions.action_id"), nullable=False),
    Column("approval_key", Text, nullable=False),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("conversation_id", UUID(as_uuid=True), nullable=False),
    Column("topic_id", UUID(as_uuid=True)),
    Column("workflow_id", Text, nullable=False),
    Column("tool", Text, nullable=False),
    Column("args", JSONB, nullable=False),
    Column("destination", Text),
    Column("summary", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("decided_by", Text),
    Column("channel", Text),
    Column("decided_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_approvals_key_workflow", "approval_key", "workflow_id"),
    Index("ix_approvals_user_status", "user_id", "status"),
)

domain_allowlist = Table(
    "domain_allowlist",
    metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("domain", Text, nullable=False),
    Column("context", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("user_id", "domain", "context", name="pk_domain_allowlist"),
)

outbox = Table(
    "outbox",
    metadata,
    Column("action_id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("conversation_id", UUID(as_uuid=True), nullable=False),
    Column("recipient", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

browser_sessions = Table(
    "browser_sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("conversation_id", UUID(as_uuid=True), nullable=False),
    Column("topic_id", UUID(as_uuid=True)),
    Column("workflow_id", Text, nullable=False),
    Column("context", Text, nullable=False),
    Column("mode", Text, nullable=False, server_default=text("'agent'")),
    Column("current_url", Text),
    Column("status", Text, nullable=False),
    Column("frame_version", Integer, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_browser_sessions_conversation", "conversation_id"),
)

browser_frames = Table(
    "browser_frames",
    metadata,
    Column(
        "session_id",
        UUID(as_uuid=True),
        ForeignKey("browser_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("version", Integer, nullable=False),
    Column("jpeg", BYTEA, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

browser_input_inbox = Table(
    "browser_input_inbox",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column(
        "session_id",
        UUID(as_uuid=True),
        ForeignKey("browser_sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("text", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

data_taint = Table(
    "data_taint",
    metadata,
    Column("conversation_id", UUID(as_uuid=True), primary_key=True),
    Column("classification", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("since", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

goals = Table(
    "goals",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("conversation_id", UUID(as_uuid=True), nullable=False),
    Column("title", Text, nullable=False),
    Column("objective", Text, nullable=False),
    Column("condition", Text),
    Column("kind", Text, nullable=False),
    Column("fire_at", DateTime(timezone=True)),
    Column("every_minutes", Integer),
    Column("status", Text, nullable=False),
    Column("last_value", Text),
    Column("last_condition", Boolean),
    Column("last_summary", Text),
    Column("last_run_at", DateTime(timezone=True)),
    Column("next_run_at", DateTime(timezone=True)),
    Column("run_count", Integer, nullable=False, server_default=text("0")),
    Column("notify_count", Integer, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_goals_user_status", "user_id", "status"),
)

notifications = Table(
    "notifications",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("conversation_id", UUID(as_uuid=True)),
    Column("goal_id", UUID(as_uuid=True)),
    Column("approval_id", UUID(as_uuid=True)),
    Column("kind", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("read_at", DateTime(timezone=True)),
    Index("ix_notifications_user_created", "user_id", "created_at"),
)

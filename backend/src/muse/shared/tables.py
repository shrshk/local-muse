"""SQLAlchemy Core tables. Every migration that changes shape updates this file too."""

from sqlalchemy import Column, DateTime, MetaData, Table, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

service_heartbeats = Table(
    "service_heartbeats",
    metadata,
    Column("service", Text, primary_key=True),
    Column("status", Text, nullable=False),
    Column("detail", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

"""Model catalog offerings — per-provider resolved model records.

One offering row per (provider_id, model_id) keeps the provider's own
observations, the operator's declared overrides, and the last resolved
view. Resolved revisions are append-only so the effective history of a
model's fields stays auditable across discovery runs and catalog
snapshots. Discovery state distinguishes a confirmed-available model,
a confirmed-unavailable one, and unknown — a failed discovery is never
flattened into "empty list".
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class ModelCatalogOffering(Base, IdMixin, TimestampMixin):
    __tablename__ = "model_catalog_offerings"
    __table_args__ = (UniqueConstraint("provider_id", "model_id"),)

    provider_id: Mapped[str] = mapped_column(String(36), index=True)
    model_id: Mapped[str] = mapped_column(String(255))  # exact request model id
    observations_json: Mapped[str] = mapped_column(Text, default="{}")
    overrides_json: Mapped[str] = mapped_column(Text, default="{}")
    resolved_json: Mapped[str] = mapped_column(Text, default="{}")
    # Explicit operator mapping into the catalog — similarity alone never
    # links a custom proxy to an official offering.
    catalog_provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    catalog_model_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    catalog_mapping_explicit: Mapped[bool] = mapped_column(Boolean, default=False)
    # available | unavailable | unknown — a failed or partial discovery is
    # unknown, never silently "unavailable".
    discovery_state: Mapped[str] = mapped_column(String(16), default="unknown")
    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # sha256 over provider type/base_url/org/key/config — a config change
    # makes prior availability observations unknown again rather than
    # manufacturing unavailability.
    config_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    snapshot_revision: Mapped[str] = mapped_column(String(64), default="")
    overrides_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)


class ModelCatalogRevision(Base):
    __tablename__ = "model_catalog_revisions"
    __table_args__ = (UniqueConstraint("offering_id", "revision"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    offering_id: Mapped[str] = mapped_column(String(36), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    resolved_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

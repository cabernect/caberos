"""Browser profiles — named, domain-scoped persistent browser state (W4).

The operator owns these. A profile holds cookies/logins for a declared set
of domains; sessions opened under a profile persist state on disk and are
domain-restricted — navigations outside the scope are blocked at request
stage. Profile names are used by `browser_open(profile=...)`.
"""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class BrowserProfile(Base, IdMixin, TimestampMixin):
    __tablename__ = "browser_profiles"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # JSON array of allowed domains — e.g. ["tradingview.com"]. An empty
    # list means unrestricted (operator's explicit choice at create time).
    allowed_domains: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

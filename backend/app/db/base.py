"""Declarative base + a single import point that pulls in every module's models so
Alembic autogenerate (and `Base.metadata.create_all` in tests) can see the full schema.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Imported for side effects: registers each module's tables on Base.metadata. Import
# order here doesn't matter -- SQLAlchemy resolves ForeignKey("table.col") strings
# lazily against the shared MetaData, not at import time. The Alembic migration that
# actually creates tables is a separate, hand-ordered concern (users/audit_log before
# trades, which FK to both).
from app.modules.audit import models as _audit_models  # noqa: E402,F401
from app.modules.auth import models as _auth_models  # noqa: E402,F401
from app.modules.market_data import models as _market_data_models  # noqa: E402,F401
from app.modules.risk import models as _risk_models  # noqa: E402,F401
from app.modules.trade_capture import models as _trade_capture_models  # noqa: E402,F401
from app.modules.valuation import models as _valuation_models  # noqa: E402,F401

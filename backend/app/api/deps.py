from app.core.db import get_session as get_db  # re-exported: single import point for routers

__all__ = ["get_db"]

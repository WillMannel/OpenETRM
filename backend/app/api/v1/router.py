from fastapi import APIRouter

from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.market_data.router import router as market_data_router
from app.modules.risk.router import router as risk_router
from app.modules.trade_capture.router import change_requests_router, reference_data_router
from app.modules.trade_capture.router import router as trade_capture_router
from app.modules.valuation.router import router as valuation_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(trade_capture_router)
api_router.include_router(change_requests_router)
api_router.include_router(reference_data_router)
api_router.include_router(market_data_router)
api_router.include_router(valuation_router)
api_router.include_router(risk_router)
api_router.include_router(audit_router)

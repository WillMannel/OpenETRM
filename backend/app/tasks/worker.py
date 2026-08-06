from typing import ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.tasks.curve_tasks import calibrate_curve
from app.tasks.risk_tasks import run_sensitivities_job, run_var_job

settings = get_settings()


class WorkerSettings:
    functions: ClassVar = [calibrate_curve, run_var_job, run_sensitivities_job]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)

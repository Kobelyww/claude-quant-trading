from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from quant_trading.api.auth import install_token_auth, workflow_command_name_for_path
from quant_trading.api.routes import dashboard, backtests, health, instruments, jobs, paper, workflows
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine
from quant_trading.workflows.runner import record_failed_workflow_command


async def workflow_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    command_name = workflow_command_name_for_path(request.method, request.url.path)
    if command_name and getattr(request.state, "authenticated", False):
        record_failed_workflow_command(
            request.app.state.engine,
            command_name,
            {"path": request.url.path, "validation_error_count": len(exc.errors())},
            "request validation failed",
        )
    return JSONResponse(status_code=400, content={"detail": jsonable_encoder(exc.errors())})


def create_app(engine: Engine | None = None, settings: AppSettings | None = None) -> FastAPI:
    settings = settings or AppSettings()
    if engine is None:
        engine = make_engine(settings.database_url)
        create_all(engine)

    app = FastAPI(title="Quant Trading Platform")
    app.state.engine = engine
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(instruments.router)
    app.include_router(backtests.router)
    app.include_router(paper.router)
    app.include_router(jobs.router)
    app.include_router(workflows.router)
    app.include_router(dashboard.router)
    install_token_auth(app, settings)
    app.add_exception_handler(RequestValidationError, workflow_validation_exception_handler)
    return app

from fastapi import FastAPI
from sqlalchemy import Engine

from quant_trading.api.auth import install_token_auth
from quant_trading.api.routes import dashboard, backtests, health, instruments, paper, workflows
from quant_trading.config import AppSettings
from quant_trading.storage.db import create_all, make_engine


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
    app.include_router(workflows.router)
    app.include_router(dashboard.router)
    install_token_auth(app, settings)
    return app

import os

from fastapi import FastAPI
from sqlalchemy import Engine

from quant_trading.api.routes import backtests, health, instruments, paper
from quant_trading.storage.db import create_all, make_engine


def create_app(engine: Engine | None = None) -> FastAPI:
    if engine is None:
        database_url = os.getenv("DATABASE_URL", "sqlite+pysqlite:///quant_trading.db")
        engine = make_engine(database_url)
        create_all(engine)

    app = FastAPI(title="Quant Trading Platform")
    app.state.engine = engine
    app.include_router(health.router)
    app.include_router(instruments.router)
    app.include_router(backtests.router)
    app.include_router(paper.router)
    return app

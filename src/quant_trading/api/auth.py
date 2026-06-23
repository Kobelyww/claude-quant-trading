from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from quant_trading.config import AppSettings

COMMAND_PATH_PATTERNS = [
    ("POST", "/workflows/import-legacy", "import_legacy"),
    ("POST", "/workflows/backtests/ma-cross", "backtest_ma_cross"),
    ("POST", "/workflows/paper/accounts", "paper_create_account"),
    ("POST", "/workflows/paper/runs/ma-cross", "paper_start_ma_cross_run"),
]


class TokenAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, settings: AppSettings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self.settings.require_auth or _is_public_path(
            request.url.path,
            self.settings.public_routes,
        ):
            request.state.authenticated = True
            return await call_next(request)

        token = _extract_token(request)
        if token != self.settings.api_token:
            request.state.authenticated = False
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        request.state.authenticated = True
        return await call_next(request)


def install_token_auth(app: FastAPI, settings: AppSettings) -> None:
    app.add_middleware(TokenAuthMiddleware, settings=settings)


def workflow_command_name_for_path(method: str, path: str) -> str | None:
    if method == "POST" and path.startswith("/workflows/paper/runs/") and path.endswith("/tick"):
        return "paper_run_tick"
    for candidate_method, candidate_path, command_name in COMMAND_PATH_PATTERNS:
        if method == candidate_method and path == candidate_path:
            return command_name
    return None


def _is_public_path(path: str, public_routes: list[str]) -> bool:
    normalized = path.rstrip("/") or "/"
    return any(normalized == (route.rstrip("/") or "/") for route in public_routes)


def _extract_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    api_token = request.headers.get("X-API-Token")
    if api_token:
        return api_token.strip()
    configured_header = getattr(request.app.state.settings, "auth_header", "Authorization")
    if configured_header not in {"Authorization", "X-API-Token"}:
        value = request.headers.get(configured_header)
        return value.strip() if value else None
    return None

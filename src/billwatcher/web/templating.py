"""Template lookup and the one place a response is rendered."""

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

PACKAGE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def render(
    request: Request, name: str, context: dict[str, Any], *, status_code: int = 200
) -> Response:
    values = {
        "request": request,
        "request_id": getattr(request.state, "request_id", ""),
        "site_name": "BillWatcherNext",
        **context,
    }
    return templates.TemplateResponse(
        request=request, name=name, context=values, status_code=status_code
    )

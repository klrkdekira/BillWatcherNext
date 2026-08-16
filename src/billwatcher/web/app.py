import hashlib
import json
import uuid
from collections.abc import Callable, Generator
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from starlette.middleware.base import RequestResponseEndpoint

from billwatcher.config import get_settings
from billwatcher.db import SessionLocal
from billwatcher.models import (
    Anomaly,
    Bill,
    BillDocument,
    BillEvent,
    BillSlugAlias,
    ChamberRecord,
    CoverageTarget,
    Document,
    DocumentVersion,
    FetchQueueItem,
    RecordChange,
    ScrapeRun,
)
from billwatcher.operations import evaluate_coverage
from billwatcher.search.lexical import search_bills
from billwatcher.version import (
    CHUNKER_VERSION,
    EXTRACTOR_VERSION,
    NORMALIZER_VERSION,
    PARSER_VERSION,
    __version__,
)

PACKAGE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
CHAMBERS = {"dewan_rakyat", "dewan_negara"}
STATUSES = {
    "introduced",
    "tabled",
    "first_read",
    "second_read",
    "committee",
    "referred",
    "third_read",
    "passed",
    "withdrawn",
    "lapsed",
    "defeated",
    "unknown",
}


def create_app(session_factory: Callable[[], Session] = SessionLocal) -> FastAPI:
    app = FastAPI(title="BillWatcherNext", version=__version__)
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    def database() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    @app.middleware("http")
    async def request_identity(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, session: Session = Depends(database)) -> Response:
        newest = session.scalars(
            select(Bill)
            .where(Bill.tombstoned_at.is_(None))
            .order_by(Bill.year.desc().nullslast(), Bill.identifier_normalized)
            .limit(10)
        ).all()
        evaluate_coverage(session)
        session.commit()
        oldest_success = session.scalar(
            select(func.min(CoverageTarget.last_success_at)).where(
                CoverageTarget.state == "healthy"
            )
        )
        return render(request, "home.html", {"bills": newest, "oldest_success": oldest_success})

    @app.get("/bills", response_class=HTMLResponse)
    @app.get("/search", response_class=HTMLResponse)
    def bills(
        request: Request,
        q: str = "",
        chamber: str | None = None,
        status: str | None = None,
        year: str | None = None,
        lang: str | None = None,
        include_superseded: bool = False,
        page: int = Query(default=1),
        session: Session = Depends(database),
    ) -> Response:
        error, parsed_year = validate_filters(q, chamber, status, year, lang, page)
        if error:
            return render(request, "error.html", {"message": error}, status_code=400)
        try:
            results = search_bills(
                session,
                query=q,
                chamber=chamber,
                status=status,
                year=parsed_year,
                page=page,
                include_superseded=include_superseded,
            )
        except ValueError as exc:
            return render(request, "error.html", {"message": str(exc)}, status_code=400)
        return render(
            request,
            "bills.html",
            {
                "results": results,
                "q": q,
                "chamber": chamber or "",
                "status": status or "",
                "year": year or "",
                "lang": lang or "",
                "include_superseded": include_superseded,
                "query_string": preserved_query(q, chamber, status, year, lang, include_superseded),
            },
        )

    @app.get("/bills/{slug}", response_class=HTMLResponse)
    def bill_detail(request: Request, slug: str, session: Session = Depends(database)) -> Response:
        bill = session.scalar(select(Bill).where(Bill.slug == slug))
        if bill is None:
            alias = session.get(BillSlugAlias, slug)
            if alias:
                target = session.get(Bill, alias.bill_id)
                if target:
                    return RedirectResponse(f"/bills/{target.slug}", status_code=308)
            return render(request, "error.html", {"message": "Bill not found"}, status_code=404)
        context = bill_context(session, bill)
        context["json_ld"] = legislation_json_ld(bill, context["chambers"])
        return render(request, "bill_detail.html", context)

    @app.get("/status", response_class=HTMLResponse)
    def status_page(request: Request, session: Session = Depends(database)) -> Response:
        targets = sorted(
            evaluate_coverage(session),
            key=lambda target: (target.chamber, target.listing_kind, target.language),
        )
        session.commit()
        anomaly_counts: dict[str, int] = {
            severity: int(count)
            for severity, count in session.execute(
                select(Anomaly.severity, func.count())
                .where(Anomaly.resolved_at.is_(None))
                .group_by(Anomaly.severity)
            ).tuples()
        }
        queue_depth = (
            session.scalar(
                select(func.count())
                .select_from(FetchQueueItem)
                .where(FetchQueueItem.state.in_(("pending", "failed", "leased")))
            )
            or 0
        )
        oldest_pending = session.scalar(
            select(func.min(FetchQueueItem.created_at)).where(
                FetchQueueItem.state.in_(("pending", "failed", "leased"))
            )
        )
        dead = (
            session.scalar(
                select(func.count())
                .select_from(FetchQueueItem)
                .where(FetchQueueItem.state == "dead")
            )
            or 0
        )
        runs = session.scalars(
            select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(10)
        ).all()
        return render(
            request,
            "status.html",
            {
                "targets": targets,
                "anomaly_counts": anomaly_counts,
                "queue_depth": queue_depth,
                "oldest_pending": oldest_pending,
                "dead": dead,
                "runs": runs,
                "versions": pipeline_versions(),
            },
        )

    @app.get("/about", response_class=HTMLResponse)
    def about(request: Request) -> Response:
        return render(request, "about.html", {"contact": get_settings().contact_email})

    @app.get("/changes", response_class=HTMLResponse)
    def changes(request: Request, session: Session = Depends(database)) -> Response:
        rows = session.scalars(
            select(RecordChange).order_by(RecordChange.changed_at.desc()).limit(100)
        ).all()
        return render(request, "changes.html", {"changes": rows})

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready(session: Session = Depends(database)) -> Response:
        try:
            session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return JSONResponse({"status": "ready"})

    @app.get("/robots.txt")
    def robots() -> PlainTextResponse:
        return PlainTextResponse("User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n")

    @app.get("/sitemap.xml")
    def sitemap(session: Session = Depends(database)) -> Response:
        base = get_settings().public_base_url.rstrip("/")
        slugs = session.scalars(
            select(Bill.slug).where(Bill.tombstoned_at.is_(None)).order_by(Bill.slug)
        ).all()
        urls = "".join(f"<url><loc>{base}/bills/{slug}</loc></url>" for slug in slugs)
        return Response(
            f'<?xml version="1.0" encoding="UTF-8"?><urlset '
            f'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
            media_type="application/xml",
        )

    @app.get("/api/v1/bills")
    def api_bills(
        q: str = "",
        chamber: str | None = None,
        status: str | None = None,
        year: int | None = None,
        page: int = 1,
        include_superseded: bool = False,
        session: Session = Depends(database),
    ) -> Response:
        error, _ = validate_filters(q, chamber, status, str(year) if year else None, None, page)
        if error:
            return JSONResponse({"error": error}, status_code=400)
        results = search_bills(
            session,
            query=q,
            chamber=chamber,
            status=status,
            year=year,
            page=page,
            include_superseded=include_superseded,
        )
        return JSONResponse(
            {
                "schema_version": "v1",
                "items": [serialize_bill(item, session) for item in results.items],
                "pagination": {
                    "page": results.page,
                    "page_size": results.page_size,
                    "total": results.total,
                },
            }
        )

    @app.get("/api/v1/bills/{identifier}")
    def api_bill(
        identifier: str, request: Request, session: Session = Depends(database)
    ) -> Response:
        bill = session.scalar(
            select(Bill).where(
                (Bill.identifier_normalized == identifier.upper()) | (Bill.slug == identifier)
            )
        )
        if bill is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        payload = serialize_bill(bill, session)
        payload["schema_version"] = "v1"
        etag = '"' + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() + '"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return JSONResponse(payload, headers={"ETag": etag})

    return app


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


def validate_filters(
    q: str,
    chamber: str | None,
    status: str | None,
    year: str | None,
    lang: str | None,
    page: int,
) -> tuple[str | None, int | None]:
    if len(q) > 200:
        return "Search query must not exceed 200 characters.", None
    if chamber and chamber not in CHAMBERS:
        return "Unknown chamber filter.", None
    if status and status not in STATUSES:
        return "Unknown status filter.", None
    if lang and lang not in {"bm", "en"}:
        return "Language must be bm or en.", None
    if page < 1:
        return "Page must be at least 1.", None
    if year:
        if not year.isdigit() or len(year) != 4:
            return "Year must contain four digits.", None
        parsed = int(year)
        if parsed < 1900 or parsed > datetime.now().year + 1:
            return "Year is outside the supported range.", None
        return None, parsed
    return None, None


def preserved_query(
    q: str,
    chamber: str | None,
    status: str | None,
    year: str | None,
    lang: str | None,
    include_superseded: bool = False,
) -> str:
    from urllib.parse import urlencode

    return urlencode(
        {
            key: value
            for key, value in {
                "q": q,
                "chamber": chamber,
                "status": status,
                "year": year,
                "lang": lang,
                "include_superseded": "1" if include_superseded else None,
            }.items()
            if value
        }
    )


def bill_context(session: Session, bill: Bill) -> dict[str, Any]:
    chambers = session.scalars(
        select(ChamberRecord)
        .where(ChamberRecord.bill_id == bill.id)
        .order_by(ChamberRecord.chamber)
    ).all()
    links = session.execute(
        select(BillDocument, Document)
        .join(Document, Document.id == BillDocument.document_id)
        .where(BillDocument.bill_id == bill.id)
    ).all()
    documents = []
    for link, document in links:
        versions = session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_no.desc())
        ).all()
        documents.append({"link": link, "document": document, "versions": versions})
    events = session.scalars(
        select(BillEvent).where(BillEvent.bill_id == bill.id).order_by(BillEvent.observed_at.desc())
    ).all()
    changes = session.scalars(
        select(RecordChange)
        .where(RecordChange.entity_type == "bill", RecordChange.entity_id == bill.id)
        .order_by(RecordChange.changed_at.desc())
    ).all()
    return {
        "bill": bill,
        "chambers": chambers,
        "documents": documents,
        "events": events,
        "changes": changes,
    }


def legislation_json_ld(bill: Bill, chambers: list[ChamberRecord]) -> dict[str, Any]:
    base = get_settings().public_base_url.rstrip("/")
    source = chambers[0].source_url if chambers else None
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Legislation",
        "@id": f"{base}/bills/{bill.slug}#bill",
        "url": f"{base}/bills/{bill.slug}",
        "name": bill.title_bm or bill.title_en or bill.identifier_raw,
        "legislationIdentifier": bill.identifier_raw,
        "legislationJurisdiction": "Malaysia",
        "legislationType": "Bill",
        "isPartOf": {"@type": "WebSite", "name": "BillWatcherNext", "url": f"{base}/"},
    }
    if bill.title_en:
        data["alternateName"] = bill.title_en
    languages = [code for code, title in (("ms", bill.title_bm), ("en", bill.title_en)) if title]
    if languages:
        data["inLanguage"] = languages
    if source:
        data["sameAs"] = source
    return data


def serialize_bill(bill: Bill, session: Session) -> dict[str, Any]:
    source_url = session.scalar(
        select(ChamberRecord.source_url)
        .where(ChamberRecord.bill_id == bill.id)
        .order_by(ChamberRecord.chamber)
        .limit(1)
    )
    return {
        "identifier": bill.identifier_normalized,
        "identifier_raw": bill.identifier_raw,
        "slug": bill.slug,
        "title_bm": bill.title_bm,
        "title_en": bill.title_en,
        "year": bill.year,
        "source_url": source_url,
        "updated_at": bill.updated_at.isoformat() if bill.updated_at else None,
        "last_checked_at": bill.last_checked_at.isoformat(),
        "last_changed_at": bill.last_changed_at.isoformat(),
    }


def pipeline_versions() -> dict[str, str]:
    return {
        "parser": PARSER_VERSION,
        "normalizer": NORMALIZER_VERSION,
        "extractor": EXTRACTOR_VERSION,
        "chunker": CHUNKER_VERSION,
    }


app = create_app()

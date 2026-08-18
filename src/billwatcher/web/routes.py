"""Public route definitions.

Handlers stay thin: they validate input, call a service, and render. Serialization shapes live
in `schemas.py` and provider wiring in `app.py`, so no route handler ever constructs a model
client or an embedding provider (HANDOFF 12.3).
"""

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Callable, Generator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import RequestResponseEndpoint

from billwatcher.config import Settings, get_settings
from billwatcher.domain.vocabulary import CHAMBERS, NORMALIZED_STATUSES
from billwatcher.models import (
    Anomaly,
    Bill,
    BillDocument,
    BillEvent,
    BillSlugAlias,
    Blob,
    ChamberRecord,
    CoverageTarget,
    Document,
    DocumentExtraction,
    DocumentRelation,
    DocumentVersion,
    FetchQueueItem,
    RecordChange,
    ScrapeRun,
)
from billwatcher.operations import evaluate_coverage
from billwatcher.search.lexical import search_bills
from billwatcher.search.rag import Answer, RagDisabled, answer_question
from billwatcher.search.semantic import SemanticSearchDisabled, hybrid_search
from billwatcher.storage.blobs import BlobNotFound
from billwatcher.web.feed import CHANGE_KINDS, CHANGES_PAGE_SIZE, recent_changes
from billwatcher.web.limits import RateLimit, RateLimiter
from billwatcher.web.retrieval import Retrieval
from billwatcher.web.schemas import (
    SCHEMA_VERSION,
    answer_payload,
    legislation_json_ld,
    pipeline_versions,
    serialize_bill,
)
from billwatcher.web.sse import SSE_HEADERS, comment, patch_elements
from billwatcher.web.templating import render, templates

STATUSES = NORMALIZED_STATUSES
# A status stream is bounded rather than endless: roughly ten minutes, then the client
# reconnects. That keeps a forgotten tab from pinning a connection and a database session.
STATUS_STREAM_INTERVAL_SECONDS = 5.0
STATUS_STREAM_TICKS = 120

TOO_MANY = "Too many requests. Please slow down; ordinary browsing and search are unaffected."


def register_routes(
    app: FastAPI,
    *,
    session_factory: Callable[[], Session],
    config: Settings,
    retrieval: Retrieval,
) -> None:
    """Attach every public route to the application."""
    search_limiter = RateLimiter(RateLimit(capacity=60, refill_per_second=1.0))
    ask_limiter = RateLimiter(RateLimit(capacity=5, refill_per_second=1 / 12))

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
        cursor: str | None = None,
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
                lang=lang,
                page=page,
                include_superseded=include_superseded,
                cursor=cursor,
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
                "statuses": sorted(STATUSES),
                # Serialized as JSON so a quote in a filter value cannot break the
                # attribute or the expression it holds.
                "signals": {
                    "q": q,
                    "chamber": chamber or "",
                    "status": status or "",
                    "year": year or "",
                    "lang": lang or "",
                },
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
        context["serve_archived_documents"] = config.serve_archived_documents
        return render(request, "bill_detail.html", context)

    @app.get("/status", response_class=HTMLResponse)
    def status_page(request: Request, session: Session = Depends(database)) -> Response:
        context = status_context(session)
        session.commit()
        return render(request, "status.html", {**context, "streaming": False})

    @app.get("/fragments/status")
    async def status_stream(request: Request) -> Response:
        """Stream the status panel so an operator watching a crawl sees it change.

        The page already rendered a correct panel server-side; this only keeps it current.
        """
        if not search_limiter.allow(client_key(request)):
            return PlainTextResponse(TOO_MANY, status_code=429)

        def snapshot() -> str:
            with session_factory() as stream_session:
                context = status_context(stream_session)
                stream_session.commit()
            return templates.get_template("_status_panel.html").render(context)

        async def events() -> AsyncIterator[str]:
            # Bounded so a forgotten tab cannot hold a connection open indefinitely; Datastar
            # reconnects on close.
            for tick in range(STATUS_STREAM_TICKS):
                if await request.is_disconnected():
                    return
                if tick:
                    await asyncio.sleep(STATUS_STREAM_INTERVAL_SECONDS)
                yield patch_elements(await run_in_threadpool(snapshot))
            yield comment("stream complete; reconnect for more")

        return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)

    @app.get("/fragments/search")
    def search_fragment(
        request: Request,
        q: str = "",
        chamber: str | None = None,
        status: str | None = None,
        year: str | None = None,
        lang: str | None = None,
        include_superseded: bool = False,
        page: int = 1,
        cursor: str | None = None,
        session: Session = Depends(database),
    ) -> Response:
        """The results region of /bills, as a Datastar patch. The page works without it."""
        if not search_limiter.allow(client_key(request)):
            return PlainTextResponse(TOO_MANY, status_code=429)
        error, parsed_year = validate_filters(q, chamber, status, year, lang, page)
        if error:
            return _fragment(templates.get_template("_search_error.html").render(message=error))
        try:
            results = search_bills(
                session,
                query=q,
                chamber=chamber,
                status=status,
                year=parsed_year,
                lang=lang,
                page=page,
                include_superseded=include_superseded,
                cursor=cursor,
            )
        except ValueError as exc:
            return _fragment(templates.get_template("_search_error.html").render(message=str(exc)))
        markup = templates.get_template("_search_results.html").render(
            results=results,
            q=q,
            query_string=preserved_query(q, chamber, status, year, lang, include_superseded),
        )
        return _fragment(markup)

    @app.get("/about", response_class=HTMLResponse)
    def about(request: Request) -> Response:
        return render(request, "about.html", {"contact": get_settings().contact_email})

    @app.get("/changes", response_class=HTMLResponse)
    def changes(
        request: Request,
        chamber: str | None = None,
        kind: str = "all",
        page: int = 1,
        session: Session = Depends(database),
    ) -> Response:
        if chamber and chamber not in CHAMBERS:
            return render(
                request, "error.html", {"message": "Unknown chamber filter."}, status_code=400
            )
        if kind not in CHANGE_KINDS:
            return render(
                request, "error.html", {"message": "Unknown change type."}, status_code=400
            )
        if page < 1:
            return render(
                request, "error.html", {"message": "Page must be at least 1."}, status_code=400
            )
        entries, has_more = recent_changes(
            session, chamber=chamber, kind=kind, page=page, page_size=CHANGES_PAGE_SIZE
        )
        return render(
            request,
            "changes.html",
            {
                "entries": entries,
                "chamber": chamber or "",
                "kind": kind,
                "page": page,
                "has_more": has_more,
                "query_string": urlencode(
                    {
                        key: value
                        for key, value in {"chamber": chamber, "kind": kind}.items()
                        if value
                    }
                ),
            },
        )

    @app.get("/semantic-search", response_class=HTMLResponse)
    def semantic_search(
        request: Request,
        q: str = "",
        chamber: str | None = None,
        status: str | None = None,
        year: str | None = None,
        include_superseded: bool = False,
        session: Session = Depends(database),
    ) -> Response:
        if retrieval.embedding_provider is None:
            return render(
                request,
                "error.html",
                {"message": "Semantic search is not enabled on this deployment."},
                status_code=404,
            )
        if not search_limiter.allow(client_key(request)):
            return render(request, "error.html", {"message": TOO_MANY}, status_code=429)
        error, parsed_year = validate_filters(q, chamber, status, year, None, 1)
        if error:
            return render(request, "error.html", {"message": error}, status_code=400)
        results = []
        if q.strip():
            try:
                results = hybrid_search(
                    session,
                    query=q,
                    settings=config,
                    provider=retrieval.embedding_provider,
                    cache=retrieval.cache,
                    chamber=chamber,
                    status=status,
                    year=parsed_year,
                    include_superseded=include_superseded,
                )
            except (ValueError, SemanticSearchDisabled) as exc:
                return render(request, "error.html", {"message": str(exc)}, status_code=400)
        return render(
            request,
            "semantic_search.html",
            {
                "results": results,
                "q": q,
                "chamber": chamber or "",
                "status": status or "",
                "year": year or "",
                "include_superseded": include_superseded,
            },
        )

    @app.get("/ask", response_class=HTMLResponse)
    def ask_form(request: Request) -> Response:
        if retrieval.answer_provider is None:
            return render(
                request,
                "error.html",
                {"message": "Generated answers are not enabled on this deployment."},
                status_code=404,
            )
        return render(request, "ask.html", {"question": "", "answer": None})

    @app.post("/ask", response_class=HTMLResponse)
    def ask(
        request: Request,
        question: str = Form(default=""),
        session: Session = Depends(database),
    ) -> Response:
        outcome = run_ask(request, session, question, config, retrieval, ask_limiter)
        if isinstance(outcome, tuple):
            message, code = outcome
            return render(request, "error.html", {"message": message}, status_code=code)
        return render(request, "ask.html", {"question": question, "answer": outcome})

    @app.post("/api/v1/ask")
    def api_ask(
        request: Request,
        payload: dict[str, Any],
        session: Session = Depends(database),
    ) -> Response:
        question = str(payload.get("question", ""))
        outcome = run_ask(request, session, question, config, retrieval, ask_limiter)
        if isinstance(outcome, tuple):
            message, code = outcome
            return JSONResponse({"error": message}, status_code=code)
        return JSONResponse(answer_payload(outcome))

    @app.get("/documents/{document_id}/versions/{version_no}")
    def archived_document(
        document_id: str,
        version_no: int,
        request: Request,
        session: Session = Depends(database),
    ) -> Response:
        """Serve our archived copy of an official document.

        Off unless the rights review in assumption A14 has concluded and been recorded
        (ADR-004). The official link on the bill page never depends on this route.

        The blob is located by digest read from the database, never from anything in the
        request path (HANDOFF 17), so no request can address a file we did not store.
        """
        if not config.serve_archived_documents:
            return render(
                request,
                "error.html",
                {
                    "message": (
                        "This service links to Parliament's official documents rather than "
                        "serving its own copies."
                    )
                },
                status_code=404,
            )
        version = session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.version_no == version_no,
            )
        )
        if version is None or version.validation_status != "accepted":
            # A quarantined version is stored for the record but never published.
            return render(
                request, "error.html", {"message": "Document version not found"}, status_code=404
            )
        blob = session.get(Blob, version.blob_sha256)
        if blob is None:
            return render(
                request, "error.html", {"message": "Document version not found"}, status_code=404
            )

        etag = f'"{version.content_sha256}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        try:
            chunks = retrieval.blob_store.stream(blob.sha256, compression=blob.compression)
        except (BlobNotFound, OSError):
            return render(
                request,
                "error.html",
                {"message": "Our copy of this document is unavailable."},
                status_code=503,
            )
        return StreamingResponse(
            chunks,
            media_type=version.media_type_detected or "application/pdf",
            headers={
                "ETag": etag,
                "Content-Length": str(version.byte_size),
                # Archived bytes are immutable, so they can be cached hard.
                "Cache-Control": "public, max-age=31536000, immutable",
                "Content-Disposition": (f'inline; filename="{_archive_filename(version)}"'),
                # Our copy is not the authority; point crawlers at the official record.
                "Link": f'<{_official_url(session, version)}>; rel="canonical"',
                "X-Robots-Tag": "noindex",
            },
        )

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
                "schema_version": SCHEMA_VERSION,
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
        payload["schema_version"] = SCHEMA_VERSION
        etag = '"' + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() + '"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return JSONResponse(payload, headers={"ETag": etag})


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
        current = next((version for version in versions if version.is_current), None)
        superseded = [version for version in versions if not version.is_current]
        excerpt, extraction_note = document_excerpt(session, current)
        relations = session.execute(
            select(DocumentRelation, Document)
            .join(Document, Document.id == DocumentRelation.to_document_id)
            .where(DocumentRelation.from_document_id == document.id)
        ).all()
        documents.append(
            {
                "link": link,
                "document": document,
                "versions": versions,
                "current": current,
                "superseded": superseded,
                "excerpt": excerpt,
                "extraction_note": extraction_note,
                "relations": relations,
            }
        )
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


EXCERPT_CHARS = 1_200


def document_excerpt(
    session: Session, version: DocumentVersion | None
) -> tuple[str | None, str | None]:
    """Return a bounded excerpt of our stored text, or an honest note about why there is none."""
    if version is None:
        return None, "We have not stored a copy of this document yet."
    extraction = session.scalar(
        select(DocumentExtraction)
        .where(
            DocumentExtraction.document_version_id == version.id,
            DocumentExtraction.is_current.is_(True),
        )
        .order_by(DocumentExtraction.created_at.desc())
        .limit(1)
    )
    if extraction is None:
        return None, "Text extraction for this version is still pending."
    if extraction.status == "empty":
        return None, (
            "This version yielded no machine-readable text; it is probably a scanned "
            "document awaiting optical character recognition."
        )
    if extraction.status != "succeeded" or not extraction.extracted_text:
        return None, "Text extraction for this version did not succeed."
    text_value = extraction.extracted_text
    excerpt = text_value[:EXCERPT_CHARS]
    note = None
    if len(text_value) > EXCERPT_CHARS:
        note = "This is a short excerpt of our stored text. The official document is linked above."
    return excerpt, note


def _fragment(markup: str) -> Response:
    """One Datastar element patch, then close."""
    return Response(patch_elements(markup), media_type="text/event-stream", headers=SSE_HEADERS)


def status_context(session: Session) -> dict[str, Any]:
    """Everything /status shows, built once so the page and the stream cannot diverge."""
    targets = sorted(
        evaluate_coverage(session),
        key=lambda target: (target.chamber, target.listing_kind, target.language),
    )
    anomaly_counts: dict[str, int] = {
        severity: int(count)
        for severity, count in session.execute(
            select(Anomaly.severity, func.count())
            .where(Anomaly.resolved_at.is_(None))
            .group_by(Anomaly.severity)
        ).tuples()
    }
    pending = FetchQueueItem.state.in_(("pending", "failed", "leased"))
    return {
        "targets": targets,
        "anomaly_counts": anomaly_counts,
        "queue_depth": session.scalar(
            select(func.count()).select_from(FetchQueueItem).where(pending)
        )
        or 0,
        "oldest_pending": session.scalar(
            select(func.min(FetchQueueItem.created_at)).where(pending)
        ),
        "dead": session.scalar(
            select(func.count()).select_from(FetchQueueItem).where(FetchQueueItem.state == "dead")
        )
        or 0,
        "runs": session.scalars(
            select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(10)
        ).all(),
        "versions": pipeline_versions(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        # Overridden to False by the first server-rendered page, which is not streaming yet.
        "streaming": True,
    }


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def run_ask(
    request: Request,
    session: Session,
    question: str,
    settings: Settings,
    retrieval: Retrieval,
    limiter: RateLimiter,
) -> Answer | tuple[str, int]:
    if retrieval.answer_provider is None or retrieval.embedding_provider is None:
        return "Generated answers are not enabled on this deployment.", 404
    if not limiter.allow(client_key(request)):
        return TOO_MANY, 429
    try:
        return answer_question(
            session,
            question=question,
            settings=settings,
            embedding_provider=retrieval.embedding_provider,
            answer_provider=retrieval.answer_provider,
            cache=retrieval.cache,
        )
    except RagDisabled:
        return "Generated answers are not enabled on this deployment.", 404
    except ValueError as error:
        return str(error), 400


def _archive_filename(version: DocumentVersion) -> str:
    """A filename built only from our own identifiers, never from upstream text."""
    return f"{version.document_id}-v{version.version_no}.pdf"


def _official_url(session: Session, version: DocumentVersion) -> str:
    document = session.get(Document, version.document_id)
    return document.canonical_source_url if document else ""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import routes_decisions, routes_health, routes_repositories
from app.api.deps import get_settings
from app.config import Settings
from app.services.data_source import NotFoundError
from app.services.errors import DataSourceError
from app.services.health import APP_VERSION

API_PREFIX = "/api/v1"
FRONTEND_ORIGIN = "http://localhost:5173"

CONTRACT_NOTES = """
Rules enforced by validators. An invalid response cannot be constructed, so a client may
treat these as guarantees rather than as conventions.

Answer shape:
- `full`, `partial` and every `refusal` except `ambiguous_entity` carry a non-empty `answer`.
- `reason_code` is `entity_not_found`, `ambiguous_entity`, `out_of_scope`, `no_decision_path`
  or `low_score` only with outcome `refusal`, and `no_verified_quote` only with outcome
  `partial`. It is null for `full`.
- `entity` is null when `reason_code` is `entity_not_found`, `ambiguous_entity` or
  `out_of_scope`.
- `ambiguous_entity` offers at least two candidates with distinct ids, and its `answer` is null.
- `full` requires at least one citation, at least one of kind SOURCE, and every citation's
  `decision_id` present in `decisions`. `no_verified_quote` forbids citations entirely.
- Every refusal lists at least one entry in `evidence_gaps`.

Confidence:
- `confidence.label` is always derived from `confidence.score`: 0.75 or more is HIGH,
  0.50 up to but not including 0.75 is MEDIUM, below 0.50 is LOW. A supplied label that
  disagrees with the score is rejected, not corrected.
- `full` requires HIGH. `partial` requires MEDIUM, or MEDIUM or LOW when `reason_code` is
  `no_verified_quote`. HIGH is never allowed on a partial.
- A scored refusal, meaning `no_decision_path` or `low_score`, requires MEDIUM or LOW. A
  refusal is never HIGH.
- `entity_not_found`, `ambiguous_entity` and `out_of_scope` are refusals that happen before
  scoring, so confidence is null for them. `no_decision_path` and `low_score` carry a score.
- If `signals.contradiction` is 1 the score is capped at 0.70. `contradiction` is a
  binary `Literal[0.0, 1.0]`, so no intermediate value can bypass the cap. The best score the
  section 7 formula can produce with contradiction 1 is 0.30 + 0.20 + 0.20 + 0.15 + 0.15
  minus 0.30, which is 0.70, so a response with contradiction 1 can never be `full`.

Graph:
- Node ids are unique, at most `MAX_GRAPH_NODES` are returned, and every edge endpoint is
  present in `nodes`. A truncated response sets `truncated` to true, so `truncated: false`
  guarantees the subgraph is complete.

Every response produced by the fixture data source carries `fixture: true`.
""".strip()


def create_app(config: Optional[Settings] = None) -> FastAPI:
    """Build the application.

    `config` overrides the process-wide settings for this application only. A test
    passes `Settings(_env_file=None)` here so the app under test cannot pick up the
    developer's `.env` and start talking to a real provider or a real database.
    """
    application = FastAPI(
        title="CodeWhy",
        version=APP_VERSION,
        description=(
            "Answers why code is the way it is, from reconstructed engineering history. "
            "Phase 0 serves synthetic fixtures only; every response is flagged `fixture: true`.\n\n"
            + CONTRACT_NOTES
        ),
    )
    if config is not None:
        application.dependency_overrides[get_settings] = lambda: config
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(routes_health.router, prefix=API_PREFIX)
    application.include_router(routes_repositories.router, prefix=API_PREFIX)
    application.include_router(routes_decisions.router, prefix=API_PREFIX)

    @application.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(DataSourceError)
    async def _data_source_error(request: Request, exc: DataSourceError) -> JSONResponse:
        # A data source that cannot answer is a server-side failure, not a statement
        # that the repository lacks the decision. Reporting it as a refusal would
        # tell the caller the history is missing when the request simply failed.
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    return application


app = create_app()

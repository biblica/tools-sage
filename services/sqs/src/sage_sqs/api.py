"""Public read-only SQS publication API plus metadata-only discovery intake."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, Response

from .discoveries import DiscoveryValidationError, accept_discovery
from .repository import Repository


def create_app(repo: Repository) -> FastAPI:
    app = FastAPI(title="SAGE Qualification Service", version="0.02a1")

    def published() -> dict:
        value = repo.current_published_bundle()
        if value is None:
            raise HTTPException(status_code=503, detail="NO_PUBLISHED_BUNDLE")
        return value

    @app.get("/health")
    def health() -> dict:
        value = repo.current_published_bundle()
        return {
            "status": "OK" if value is not None else "DEGRADED",
            "service_version": "0.02a1",
            "bundle_revision": int(value["bundle_revision"]) if value is not None else 0,
        }

    @app.get("/profiles")
    def profiles() -> list[dict]:
        return list(published().get("profiles") or [])

    @app.get("/profiles/{profile_id}")
    def profile(profile_id: str) -> dict:
        for row in published().get("profiles") or []:
            if row.get("profile_id") == profile_id:
                return row
        raise HTTPException(status_code=404, detail="UNKNOWN_PROFILE")

    @app.get("/models")
    def models() -> list[dict]:
        return list(published().get("models") or [])

    @app.get("/qualifications")
    def qualifications(
        profile_id: str | None = None,
        capability: str | None = None,
        model_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        rows = list(published().get("qualifications") or [])
        if profile_id is not None:
            rows = [row for row in rows if row.get("profile_id") == profile_id]
        if capability is not None:
            rows = [row for row in rows if row.get("capability") == capability]
        if model_id is not None:
            rows = [row for row in rows if row.get("model_id") == model_id]
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    @app.get("/bundle")
    def bundle(request: Request, response: Response):
        value = published()
        etag = f'"{value["bundle_sha256"]}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        response.headers["ETag"] = etag
        return value

    @app.post("/discoveries", status_code=202)
    async def discoveries(request: Request) -> dict:
        payload = await request.json()
        try:
            receipt = accept_discovery(repo, payload)
        except DiscoveryValidationError:
            raise HTTPException(status_code=400, detail="INVALID_DISCOVERY")
        return {"status": "accepted", "discovery_id": receipt.discovery_id}

    return app

import os
from hmac import compare_digest
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from validation_engine import ValidationError, decode_upload, evaluate
from validation_lab import run_lab
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, StringConstraints

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
bearer = HTTPBearer(auto_error=False)
PostcodeKey = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{5,7}$")]
ReleaseID = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]


class PostcodeBatch(BaseModel):
    postcode_keys: list[PostcodeKey] = Field(min_length=1, max_length=5000)
    postcode_release: ReleaseID | None = None


def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    token = os.environ.get("SCV_LOOKUP_TOKEN")
    if not token:
        raise HTTPException(503, "Lookup service unavailable")
    if not credentials or not compare_digest(credentials.credentials.encode(), token.encode()):
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})


@app.get("/health")
def health():
    return {"status": "ok", "engine": "python", "version": "python-migration-1"}


@app.post("/postcodes/lookup", dependencies=[Depends(authenticate)])
def lookup(batch: PostcodeBatch):
    keys = list(dict.fromkeys(batch.postcode_keys))
    try:
        with psycopg.connect(sslmode="verify-full", connect_timeout=10) as database:
            database.execute("SET LOCAL statement_timeout = '10s'")
            release = batch.postcode_release
            if release is None:
                active = database.execute(
                    "SELECT release_id FROM scv_reference.current_postcode_release"
                ).fetchone()
                if active is None:
                    raise HTTPException(503, "No active postcode release")
                release = active[0]
            exists = database.execute(
                "SELECT EXISTS (SELECT 1 FROM scv_reference.postcode WHERE release_id = %s)",
                (release,),
            ).fetchone()[0]
            if not exists:
                raise HTTPException(503, "Postcode release unavailable")
            found = database.execute(
                """
                SELECT postcode_key FROM scv_reference.postcode
                WHERE release_id = %s AND postcode_key = ANY(%s::text[])
                  AND termination_month IS NULL
                """,
                (release, keys),
            )
            matched = {row[0] for row in found}
    except psycopg.Error:
        raise HTTPException(503, "Postcode database unavailable") from None

    return {
        "postcode_release": release,
        "results": {key: "Found" if key in matched else "Not Found" for key in keys},
    }


@app.exception_handler(ValidationError)
async def invalid_file(request: Request, error: ValidationError):
    return JSONResponse({"message": str(error), "code": error.code}, status_code=400)


class ValidationRun(BaseModel):
    source: str = Field(max_length=20_000_000)
    selected: list[str] | None = None


class LabRun(BaseModel):
    code: str
    records: list[dict[str, str]] = Field(max_length=1000)
    file: str = Field(default="", max_length=20_000_000)
    condition: dict[str, str] = Field(default_factory=dict)


def postcode_lookup(keys):
    # Pin all chunks to the same release even if the active release changes.
    unique = list(dict.fromkeys(keys))
    release = None
    missing = []
    for start in range(0, len(unique), 5000):
        result = lookup(PostcodeBatch(postcode_keys=unique[start:start + 5000], postcode_release=release))
        release = result["postcode_release"]
        missing.extend(key for key, status in result["results"].items() if status == "Not Found")
    return {"release": release, "missing": missing}


@app.post("/api/import/inspect", dependencies=[Depends(authenticate)])
async def inspect_upload(request: Request):
    body = await request.body()
    if len(body) > 20_000_000:
        raise HTTPException(413, "Online test files must be smaller than 20 MB")
    return decode_upload(body)


@app.post("/api/validate", dependencies=[Depends(authenticate)])
def validate(run: ValidationRun):
    return evaluate(run.source, run.selected, postcode_lookup)


@app.post("/api/lab/run", dependencies=[Depends(authenticate)])
def lab(run: LabRun):
    return run_lab(run.code, run.records, run.file, run.condition, postcode_lookup)

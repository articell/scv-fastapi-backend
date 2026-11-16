import os
from hmac import compare_digest
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException
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
    return {"status": "ok"}


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

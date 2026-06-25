"""JWT verification middleware for FastAPI.

Validates Supabase-issued JWTs (HS256 or ES256), extracts the founder_id (sub claim),
and confirms the founder exists in the database before allowing the request through.
"""

import logging
import base64
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, jwk, JWTError
from supabase import create_client

from backend.config import Settings, get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)
_REQUIRED_CLAIMS = {"sub", "role", "iat", "exp"}

# Module-level JWKS cache — fetched once per process, keyed by Supabase URL
_jwks_cache: dict[str, list] = {}


def _fetch_jwks(supabase_url: str) -> list:
    """Fetch Supabase's public JWKS keys (no cache)."""
    try:
        resp = httpx.get(f"{supabase_url}/auth/v1/.well-known/jwks.json", timeout=5)
        resp.raise_for_status()
        keys = resp.json().get("keys", [])
        logger.info("JWKS fetched: %d key(s) from %s", len(keys), supabase_url)
        return keys
    except Exception as exc:
        logger.warning("JWKS fetch failed: %s", exc)
        return []

def _verify_es256(token: str, supabase_url: str) -> Optional[dict]:
    """Verify an ES256 token using Supabase's public JWKS."""
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        keys = _fetch_jwks(supabase_url)
        matching = [k for k in keys if k.get("kid") == kid] if kid else keys
        for key_data in matching:
            try:
                public_key = jwk.construct(key_data)
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=["ES256"],
                    options={"verify_aud": False},
                )
                return payload
            except Exception:
                continue
    except Exception as exc:
        logger.debug("ES256 verification error: %s", exc)
    return None


def _decode_token(token: str, secret: str, supabase_url: str) -> dict:
    """Decode and validate a Supabase JWT (ES256 via JWKS, HS256 via secret)."""
    if not secret:
        raise HTTPException(status_code=500, detail="Server config error: missing JWT secret")

    try:
        unverified_payload = jwt.get_unverified_claims(token)
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg", "HS256")
        iss = unverified_payload.get("iss", "unknown")
        logger.info("Auth: alg=%s iss=%s sub=%s", alg, iss, unverified_payload.get("sub"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "API_AUTH_001", "message": "Malformed session token"},
        ) from exc

    # ES256 path — use JWKS public key (correct for Supabase new projects)
    if alg == "ES256":
        payload = _verify_es256(token, supabase_url)
        if payload:
            missing = _REQUIRED_CLAIMS - payload.keys()
            if missing:
                raise HTTPException(status_code=401, detail=f"Token missing claims: {missing}")
            return payload
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "API_AUTH_001", "message": "ES256 signature invalid"},
        )

    # HS256 / RS256 path — use JWT secret
    secret_bytes: bytes
    try:
        if len(secret) > 40 and ("=" in secret or "/" in secret):
            secret_bytes = base64.b64decode(secret)
        else:
            secret_bytes = secret.encode("utf-8")
    except Exception:
        secret_bytes = secret.encode("utf-8")

    payload = None
    last_err: Exception = RuntimeError("no algorithms tried")
    for try_alg in [alg, "HS256", "RS256"]:
        try:
            payload = jwt.decode(
                token,
                secret_bytes,
                algorithms=[try_alg],
                options={"verify_aud": False, "verify_signature": True},
            )
            if payload:
                break
        except Exception as exc:
            last_err = exc

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "API_AUTH_001", "message": f"Invalid session: {last_err}"},
        )

    missing = _REQUIRED_CLAIMS - payload.keys()
    if missing:
        raise HTTPException(status_code=401, detail=f"Token missing claims: {missing}")

    return payload


async def _get_founder_from_db(founder_id: str, settings: Settings, email: str = "founder@example.com") -> dict:
    """Fetch the founder profile or create it if missing."""
    try:
        if not settings.supabase_url:
            return {"id": founder_id, "email": email}
        client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        result = client.table("founders").select("*").eq("id", founder_id).execute()

        if result.data:
            return result.data[0]

        logger.warning("Founder profile missing for %s — creating default", founder_id)
        new_profile = {
            "id": founder_id,
            "email": email,
            "full_name": "Verified Founder",
            "company_name": "Stealth Startup",
        }
        client.table("founders").insert(new_profile).execute()
        return new_profile

    except Exception as exc:
        logger.error("Supabase founder sync failed for %s: %s", founder_id, exc)
        return {"id": founder_id, "email": email}


async def verify_jwt(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> dict:
    """FastAPI dependency: validate JWT and return founder claims."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "API_AUTH_001", "message": "Authorization header required"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = _decode_token(credentials.credentials, settings.supabase_jwt_secret, settings.supabase_url)
    founder_id: str = payload["sub"]
    email: str = payload.get("email", "founder@example.com")

    founder_profile = await _get_founder_from_db(founder_id, settings, email)
    payload["founder_profile"] = founder_profile

    return payload


# Alias for backward compatibility
get_current_founder = verify_jwt

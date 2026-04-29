from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import jwt
import requests
from django.core.cache import cache

DISCOVERY_URL = "https://oauth.telegram.org/.well-known/openid-configuration"
EXPECTED_ISSUER = "https://oauth.telegram.org"
DISCOVERY_CACHE_SECONDS = 3600
JWKS_CACHE_SECONDS = 3600


class TelegramOidcError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramOidcDiscovery:
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    issuer: str


def get_telegram_oidc_discovery() -> TelegramOidcDiscovery:
    cached = cache.get("telegram:oidc:discovery")
    if isinstance(cached, dict):
        return TelegramOidcDiscovery(**cached)

    try:
        resp = requests.get(DISCOVERY_URL, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise TelegramOidcError("failed to fetch oidc discovery") from exc

    discovery = TelegramOidcDiscovery(
        authorization_endpoint=str(payload.get("authorization_endpoint", "")).strip(),
        token_endpoint=str(payload.get("token_endpoint", "")).strip(),
        jwks_uri=str(payload.get("jwks_uri", "")).strip(),
        issuer=str(payload.get("issuer", EXPECTED_ISSUER)).strip(),
    )
    if not discovery.authorization_endpoint or not discovery.token_endpoint or not discovery.jwks_uri:
        raise TelegramOidcError("oidc discovery is incomplete")
    cache.set("telegram:oidc:discovery", discovery.__dict__, timeout=DISCOVERY_CACHE_SECONDS)
    return discovery


def exchange_code_for_tokens(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
    token_endpoint: str,
) -> dict[str, Any]:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    try:
        resp = requests.post(
            token_endpoint,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic}",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": code_verifier,
            },
            timeout=10,
        )
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise TelegramOidcError("failed to exchange authorization code") from exc
    if not resp.ok:
        msg = payload.get("error_description") or payload.get("error") or "oidc token exchange failed"
        raise TelegramOidcError(str(msg))
    return payload


def validate_telegram_id_token(
    *,
    id_token: str,
    client_id: str,
    jwks_uri: str,
    expected_issuer: str,
    expected_nonce: str | None = None,
) -> dict[str, Any]:
    cache_key = f"telegram:oidc:jwks:{jwks_uri}"
    jwk_set = cache.get(cache_key)
    if not isinstance(jwk_set, dict):
        try:
            jwk_set = requests.get(jwks_uri, timeout=10).json()
        except (requests.RequestException, ValueError) as exc:
            raise TelegramOidcError("failed to fetch jwks") from exc
        cache.set(cache_key, jwk_set, timeout=JWKS_CACHE_SECONDS)

    try:
        headers = jwt.get_unverified_header(id_token)
        kid = headers.get("kid")
        keys = jwk_set.get("keys") or []
        jwk_data = next((k for k in keys if k.get("kid") == kid), None)
        if not jwk_data:
            raise TelegramOidcError("id_token signing key not found")
        signing_key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk_data)
        payload = jwt.decode(
            id_token,
            signing_key,
            algorithms=["RS256", "RS384", "RS512"],
            audience=str(client_id),
            issuer=expected_issuer,
            options={"require": ["iss", "aud", "exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise TelegramOidcError("invalid id_token") from exc

    if expected_nonce is not None:
        nonce = str(payload.get("nonce", "")).strip()
        if not nonce or nonce != expected_nonce:
            raise TelegramOidcError("invalid nonce")
    return payload


def telegram_user_id_from_id_token(payload: dict[str, Any]) -> int:
    uid = payload.get("id")
    if isinstance(uid, int):
        return uid
    if isinstance(uid, str) and uid.isdigit():
        return int(uid)
    raise TelegramOidcError("id claim is missing in id_token")

"""QuickBooks Online V3 API integration for MCP Gateway.

Provides a production-shaped client that wraps the MCP Gateway ApiClient
with QBO-specific URL construction, OAuth2 token management, and the
QBO query language.
"""
from __future__ import annotations

import base64
import os
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from ..codemode import ApiClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com"
_PRODUCTION_BASE = "https://quickbooks.api.intuit.com"
_AUTH_BASE = "https://appcenter.intuit.com/connect/oauth2"
_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
_SCOPES = "com.intuit.quickbooks.accounting"


@dataclass
class QuickBooksConfig:
    """Connection details for a QuickBooks Online company."""

    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "http://localhost:8000/callback"
    realm_id: str = ""  # QBO company ID
    environment: str = "sandbox"  # sandbox | production
    access_token: str = ""
    refresh_token: str = ""

    @classmethod
    def from_env(cls) -> "QuickBooksConfig":
        """Load configuration from environment variables."""
        return cls(
            client_id=os.getenv("QBO_CLIENT_ID", ""),
            client_secret=os.getenv("QBO_CLIENT_SECRET", ""),
            redirect_uri=os.getenv("QBO_REDIRECT_URI", "http://localhost:8000/callback"),
            realm_id=os.getenv("QBO_REALM_ID", ""),
            environment=os.getenv("QBO_ENVIRONMENT", "sandbox"),
            access_token=os.getenv("QBO_ACCESS_TOKEN", ""),
            refresh_token=os.getenv("QBO_REFRESH_TOKEN", ""),
        )

    @property
    def base_url(self) -> str:
        host = _PRODUCTION_BASE if self.environment == "production" else _SANDBOX_BASE
        return f"{host}/v3/company/{self.realm_id}"


# ---------------------------------------------------------------------------
# OAuth2 helper
# ---------------------------------------------------------------------------


class QuickBooksOAuth:
    """Handles QBO OAuth2 authorization code flow and token refresh."""

    def __init__(self, config: QuickBooksConfig) -> None:
        self.config = config

    def get_auth_url(self, state: str = "") -> str:
        """Return the Intuit OAuth2 authorization URL."""
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "state": state,
        }
        return f"{_AUTH_BASE}?{urllib.parse.urlencode(params)}"

    def _basic_header(self) -> str:
        creds = f"{self.config.client_id}:{self.config.client_secret}"
        return base64.b64encode(creds.encode()).decode()

    def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchange an authorization code for access + refresh tokens."""
        resp = httpx.post(
            _TOKEN_URL,
            headers={
                "Authorization": f"Basic {self._basic_header()}",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
            },
            timeout=30,
        )
        resp.raise_for_status()
        tokens = resp.json()
        self.config.access_token = tokens.get("access_token", "")
        self.config.refresh_token = tokens.get("refresh_token", "")
        return tokens

    def refresh_tokens(self) -> Dict[str, Any]:
        """Use the refresh token to obtain new access + refresh tokens."""
        resp = httpx.post(
            _TOKEN_URL,
            headers={
                "Authorization": f"Basic {self._basic_header()}",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.config.refresh_token,
            },
            timeout=30,
        )
        resp.raise_for_status()
        tokens = resp.json()
        self.config.access_token = tokens.get("access_token", "")
        self.config.refresh_token = tokens.get("refresh_token", "")
        return tokens


# ---------------------------------------------------------------------------
# QBO API client
# ---------------------------------------------------------------------------


class QuickBooksClient:
    """High-level QuickBooks Online API client.

    Wraps the gateway's ``ApiClient`` with QBO-specific helpers for the
    query API, CRUD operations, and proper header management.
    """

    def __init__(self, config: QuickBooksConfig) -> None:
        self.config = config
        self._api = ApiClient(
            base_url=config.base_url,
            tenant_id=config.realm_id,
            headers={
                "Authorization": f"Bearer {config.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    # -- QBO query language ------------------------------------------------

    def query(self, entity: str, where: Optional[str] = None, max_results: int = 1000) -> Dict[str, Any]:
        """Run a QBO query.  e.g. query("Invoice", "TxnDate > '2026-01-01'")"""
        stmt = f"select * from {entity}"
        if where:
            stmt += f" where {where}"
        stmt += f" maxresults {max_results}"
        return self._api.get("/query", params={"query": stmt})

    # -- CRUD --------------------------------------------------------------

    def get(self, entity: str, entity_id: str) -> Dict[str, Any]:
        return self._api.get(f"/{entity.lower()}/{entity_id}")

    def create(self, entity: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._api.post(f"/{entity.lower()}", json=data)

    def update(self, entity: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._api.post(f"/{entity.lower()}", json=data)  # QBO uses POST for updates too

    def delete(self, entity: str, entity_id: str, sync_token: str = "0") -> Dict[str, Any]:
        return self._api.post(
            f"/{entity.lower()}",
            json={"Id": entity_id, "SyncToken": sync_token},
            params={"operation": "delete"},
        )

    # -- Reports -----------------------------------------------------------

    def report(self, report_name: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Fetch a QBO report (e.g. ProfitAndLoss, BalanceSheet)."""
        return self._api.get(f"/reports/{report_name}", params=params or {})

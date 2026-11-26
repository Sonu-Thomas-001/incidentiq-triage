"""ServiceNow Table API client (read + one narrowly scoped write).

Only the calls the project needs: list/read incidents, list assignment groups, PATCH
`assignment_group`. Credentials are server-side; they are never logged or returned.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings
from app.core.errors import IntegrationDisabledError, UpstreamError, ValidationFailure

logger = logging.getLogger(__name__)

SYS_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")
INCIDENT_FIELDS = (
    "sys_id,number,short_description,description,state,priority,impact,urgency,category,"
    "assignment_group,correlation_id,sys_created_on,sys_updated_on"
)
GROUP_FIELDS = "sys_id,name,description,active"
MAX_RETRY_AFTER = 30.0
RETRY_STATUSES = {502, 503, 504}


def validate_sys_id(value: str) -> str:
    if not SYS_ID_RE.fullmatch(value or ""):
        raise ValidationFailure("sys_id must be 32 hexadecimal characters")
    return value.lower()


def normalize_instance_url(url: str | None, allow_any_host: bool = False) -> str:
    """Return `https://host` or raise. Blocks plain http, credentials in URLs and foreign hosts (SSRF)."""
    if not url:
        raise IntegrationDisabledError("SERVICENOW_INSTANCE_URL is not configured")
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise ValidationFailure("SERVICENOW_INSTANCE_URL must be an https URL without credentials")
    if not allow_any_host and not host.endswith(".service-now.com"):
        raise ValidationFailure("SERVICENOW_INSTANCE_URL host must end with .service-now.com")
    port = f":{parts.port}" if parts.port else ""
    return f"https://{host}{port}"


def sanitize_query_text(value: str, limit: int = 100) -> str:
    """Encoded-query operators (^, newlines) are stripped so user text cannot widen a filter."""
    return re.sub(r"[\^\r\n]", " ", value or "").strip()[:limit]


class ServiceNowClient(Protocol):
    host: str

    def list_incidents(
        self, *, limit: int, offset: int, state: str | None, query: str | None, group: str | None
    ) -> tuple[list[dict[str, Any]], int | None]: ...
    def get_incident(self, sys_id: str) -> dict[str, Any]: ...
    def list_groups(
        self, *, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int | None]: ...
    def update_assignment_group(self, sys_id: str, group_sys_id: str) -> dict[str, Any]: ...


class HttpServiceNowClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base = normalize_instance_url(
            settings.servicenow_instance_url, settings.servicenow_allow_any_host
        )
        self.host = urlsplit(self.base).hostname or ""
        self.max_retries = settings.servicenow_max_retries
        self._sleep = sleep
        self._settings = settings
        self._token: str | None = None
        self._auth: httpx.Auth | None = None
        if settings.servicenow_auth == "basic":
            user, pwd = settings.servicenow_username, settings.servicenow_password
            if not user or not pwd or not pwd.get_secret_value():
                raise IntegrationDisabledError("ServiceNow credentials are not configured")
            self._auth = httpx.BasicAuth(user, pwd.get_secret_value())
        elif not (
            settings.servicenow_oauth_client_id
            and settings.servicenow_oauth_client_secret
            and settings.servicenow_username
            and settings.servicenow_password
        ):
            raise IntegrationDisabledError("ServiceNow OAuth credentials are not configured")
        self._http = httpx.Client(
            base_url=self.base,
            timeout=settings.servicenow_timeout_seconds,
            transport=transport,
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    def close(self) -> None:
        self._http.close()

    def _bearer(self) -> dict[str, str]:
        if self._token is None:
            s = self._settings
            r = self._http.post(
                "/oauth_token.do",
                data={
                    "grant_type": "password",
                    "client_id": s.servicenow_oauth_client_id,
                    "client_secret": s.servicenow_oauth_client_secret.get_secret_value(),  # type: ignore[union-attr]
                    "username": s.servicenow_username,
                    "password": s.servicenow_password.get_secret_value(),  # type: ignore[union-attr]
                },
            )
            if r.status_code != 200:
                raise UpstreamError(
                    "ServiceNow OAuth token request was rejected",
                    status_code=502,
                    code="UPSTREAM_AUTH_FAILED",
                )
            self._token = r.json().get("access_token")
        return {"Authorization": f"Bearer {self._token}"}

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                headers = self._bearer() if self._auth is None else None
                resp = self._http.request(method, path, auth=self._auth, headers=headers, **kw)
            except httpx.TimeoutException as exc:
                if attempt < attempts:
                    self._sleep(min(0.5 * 2 ** (attempt - 1), MAX_RETRY_AFTER))
                    continue
                raise UpstreamError(
                    "ServiceNow request timed out", status_code=504, code="UPSTREAM_TIMEOUT"
                ) from exc
            except httpx.HTTPError as exc:
                raise UpstreamError(
                    f"ServiceNow is unreachable ({type(exc).__name__})",
                    status_code=502,
                    code="UPSTREAM_UNREACHABLE",
                ) from exc
            retry_after = _retry_after(resp)
            if resp.status_code == 429:
                if (
                    attempt < attempts
                    and retry_after is not None
                    and retry_after <= MAX_RETRY_AFTER
                ):
                    self._sleep(retry_after)
                    continue
                raise UpstreamError(
                    "ServiceNow rate limit reached",
                    status_code=429,
                    code="UPSTREAM_RATE_LIMITED",
                    retry_after=retry_after,
                )
            # PATCH of a fixed value is idempotent, so retrying gateway errors is safe here.
            retryable = resp.status_code in RETRY_STATUSES or (
                resp.status_code == 500
                and method == "GET"  # dev instances often 500 once after idle
            )
            if retryable and attempt < attempts:
                self._sleep(min(retry_after or 0.5 * 2 ** (attempt - 1), MAX_RETRY_AFTER))
                continue
            return self._check(resp)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _check(resp: httpx.Response) -> httpx.Response:
        if resp.status_code < 400:
            return resp
        logger.warning(
            "servicenow error status=%s path=%s", resp.status_code, resp.request.url.path
        )
        if resp.status_code == 401:
            raise UpstreamError(
                "ServiceNow rejected the credentials",
                status_code=502,
                code="UPSTREAM_AUTH_FAILED",
            )
        if resp.status_code == 403:
            raise UpstreamError(
                "The ServiceNow account lacks permission for this operation",
                status_code=502,
                code="UPSTREAM_FORBIDDEN",
            )
        if resp.status_code == 404:
            raise UpstreamError(
                "ServiceNow record not found", status_code=404, code="UPSTREAM_NOT_FOUND"
            )
        raise UpstreamError(
            f"ServiceNow returned HTTP {resp.status_code}",
            status_code=502,
            code="UPSTREAM_ERROR",
        )

    @staticmethod
    def _result(resp: httpx.Response) -> Any:
        try:
            return resp.json()["result"]
        except (ValueError, KeyError) as exc:
            raise UpstreamError(
                "ServiceNow returned an unexpected payload",
                status_code=502,
                code="UPSTREAM_BAD_PAYLOAD",
            ) from exc

    @staticmethod
    def _total(resp: httpx.Response) -> int | None:
        raw = resp.headers.get("X-Total-Count")
        return int(raw) if raw and raw.isdigit() else None

    def list_incidents(self, *, limit, offset, state, query, group):
        parts = ["ORDERBYDESCsys_created_on"]
        if state:
            parts.insert(0, f"state={sanitize_query_text(state, 10)}")
        if group:
            parts.insert(0, f"assignment_group={validate_sys_id(group)}")
        if query:
            parts.insert(0, f"short_descriptionLIKE{sanitize_query_text(query)}")
        resp = self._request(
            "GET",
            "/api/now/table/incident",
            params={
                "sysparm_limit": limit,
                "sysparm_offset": offset,
                "sysparm_fields": INCIDENT_FIELDS,
                "sysparm_exclude_reference_link": "true",
                "sysparm_query": "^".join(parts),
            },
        )
        return self._result(resp), self._total(resp)

    def get_incident(self, sys_id: str) -> dict[str, Any]:
        resp = self._request(
            "GET",
            f"/api/now/table/incident/{validate_sys_id(sys_id)}",
            params={"sysparm_fields": INCIDENT_FIELDS, "sysparm_exclude_reference_link": "true"},
        )
        return self._result(resp)

    def list_groups(self, *, limit, offset):
        resp = self._request(
            "GET",
            "/api/now/table/sys_user_group",
            params={
                "sysparm_limit": limit,
                "sysparm_offset": offset,
                "sysparm_fields": GROUP_FIELDS,
                "sysparm_exclude_reference_link": "true",
                "sysparm_query": "active=true^ORDERBYname",
            },
        )
        return self._result(resp), self._total(resp)

    def update_assignment_group(self, sys_id: str, group_sys_id: str) -> dict[str, Any]:
        resp = self._request(
            "PATCH",
            f"/api/now/table/incident/{validate_sys_id(sys_id)}",
            params={"sysparm_fields": INCIDENT_FIELDS, "sysparm_exclude_reference_link": "true"},
            json={"assignment_group": validate_sys_id(group_sys_id)},
        )
        return self._result(resp)


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None

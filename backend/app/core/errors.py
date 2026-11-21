from typing import Any


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class AuthenticationError(AppError):
    status_code = 401
    code = "UNAUTHENTICATED"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class InvalidTransitionError(AppError):
    status_code = 409
    code = "INVALID_TRANSITION"


class StaleVersionError(AppError):
    status_code = 409
    code = "STALE_VERSION"


class ValidationFailure(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class IntegrationDisabledError(AppError):
    status_code = 503
    code = "INTEGRATION_DISABLED"


class WriteDisabledError(AppError):
    status_code = 409
    code = "WRITE_DISABLED"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class UpstreamError(AppError):
    """Failure talking to an external system; status/code vary with the cause."""

    status_code = 502
    code = "UPSTREAM_ERROR"

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        code: str = "UPSTREAM_ERROR",
        details: Any = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, details)
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after

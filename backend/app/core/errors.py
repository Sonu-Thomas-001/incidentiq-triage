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

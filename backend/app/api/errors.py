from typing import Any


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        kind: str,
        message: str,
        detail: Any = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind
        self.message = message
        self.detail = detail


def error_body(kind: str, message: str, detail: Any = None) -> dict:
    return {"error": {"kind": kind, "message": message, "detail": detail}}


class NotFoundError(AppError):
    def __init__(self, message: str = "Data tidak ditemukan."):
        super().__init__(404, "NotFound", message)

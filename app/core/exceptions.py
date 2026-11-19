"""Domain exceptions and error models."""

from typing import Any, Dict, Optional
from fastapi import HTTPException, status


class CiteVerifyException(Exception):
    """Base exception for all CiteVerify errors."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class DocumentNotFoundError(CiteVerifyException):
    """Raised when a requested document does not exist."""

    def __init__(self, document_id: str):
        super().__init__(
            message=f"Document with ID '{document_id}' not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"document_id": document_id},
        )


class ResultNotFoundError(CiteVerifyException):
    """Raised when a verification result does not exist."""

    def __init__(self, result_id: str):
        super().__init__(
            message=f"Result with ID '{result_id}' not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"result_id": result_id},
        )


class JobNotFoundError(CiteVerifyException):
    """Raised when a job does not exist."""

    def __init__(self, job_id: str):
        super().__init__(
            message=f"Job with ID '{job_id}' not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"job_id": job_id},
        )


class PipelineExecutionError(CiteVerifyException):
    """Raised when a pipeline stage encounters an unrecoverable failure."""

    def __init__(self, stage_name: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"Pipeline error in stage '{stage_name}': {message}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"stage": stage_name, **(details or {})},
        )


class RateLimitExceededError(CiteVerifyException):
    """Raised when external or internal rate limits are exceeded."""

    def __init__(self, service: str, retry_after: int = 60):
        super().__init__(
            message=f"Rate limit exceeded for '{service}'. Try again in {retry_after}s.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details={"service": service, "retry_after": retry_after},
        )


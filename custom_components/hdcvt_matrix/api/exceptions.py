"""Errors raised by the matrix client."""

from __future__ import annotations


class MatrixError(Exception):
    """Base error for all matrix client failures."""


class MatrixConnectionError(MatrixError):
    """The matrix could not be reached."""


class MatrixResponseError(MatrixError):
    """The matrix replied with something we cannot parse or did not expect."""


class MatrixAuthError(MatrixError):
    """The matrix rejected the supplied credentials."""

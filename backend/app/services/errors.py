"""Errors shared across the data-source layer.

Kept in its own module so services can raise them without importing each other.
"""

from __future__ import annotations


class DataSourceError(RuntimeError):
    """A data source could not produce a response.

    This means the request failed, not that the repository lacks an answer. The API
    surfaces it as a server error so an outage is never reported as missing history.
    """

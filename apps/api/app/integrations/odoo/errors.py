"""Safe, normalized connector error codes (Phase 2C).

Raw upstream error bodies, library exception reprs, and remote tracebacks
must never reach the API. Every failure is mapped to one of these codes.
"""

SAFE_ERROR_CODES = frozenset(
    {
        "invalid_configuration",
        "dns_resolution_failed",
        "blocked_destination",
        "connection_timeout",
        "tls_error",
        "server_unreachable",
        "not_odoo",
        "unsupported_response",
        "authentication_failed",
        "access_denied",
        "database_not_found",
        "json2_unavailable",
        "unsupported_version",
        "internal_connector_error",
    }
)


class ConnectorError(Exception):
    """Failure with a safe normalized code. Message stays server-side only."""

    def __init__(self, code: str, detail: str | None = None):
        if code not in SAFE_ERROR_CODES:
            code = "internal_connector_error"
        self.code = code
        # `detail` is for server-side context only and must never be
        # serialized into an API response or audit record.
        super().__init__(code if detail is None else f"{code}: {detail}")

"""Centralized outbound network security policy for Odoo connectivity.

Every outbound Odoo request MUST pass through this policy first.

Protections:
- scheme restricted to http/https (https required in production)
- no embedded credentials, query strings, or fragments
- hostname resolved and ALL resolved IPs inspected; loopback, private,
  link-local, multicast, unspecified, reserved, and cloud-metadata
  destinations are rejected by default
- DNS is validated immediately before the request; redirects are disabled
  at the HTTP client level

Accurate statement of the current protection level:
- DNS is revalidated immediately before EVERY outbound request (httpx
  request event hook in http.build_client), not just once per test.
- Redirects are disabled and can never be enabled.
- ALL resolved addresses that are not globally routable are rejected
  (default-deny via `not ip.is_global`), covering loopback, RFC1918,
  link-local, CGNAT 100.64.0.0/10, benchmarking 198.18.0.0/15,
  documentation/reserved ranges, multicast, unspecified, and non-global
  IPv6 — for both IPv4 and IPv6.
- Known cloud metadata endpoints are additionally blocked explicitly as
  defense-in-depth.

DNS rebinding: the validated IP is pinned to the actual TCP connection by
`http.PinningTransport` — the transport resolves and validates the host
ONCE, then connects to exactly that IP (Host header and TLS SNI keep the
original hostname, so certificate verification is unchanged). There is no
second, unvalidated resolution between check and connect, closing the
previous TOCTOU window.
Private or internal Odoo servers will require an explicit allowlist or
the Modeem Bridge/Gateway design in a later phase — there is deliberately
no private-network bypass here.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

from .errors import ConnectorError

# Cloud metadata endpoints commonly targeted by SSRF.
_METADATA_ADDRESSES = frozenset({"169.254.169.254", "fd00:ec2::254", "100.100.100.200"})


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Default-deny: anything not globally routable is blocked.

    `is_global` already excludes loopback, RFC1918, link-local, CGNAT
    (100.64.0.0/10), benchmarking (198.18.0.0/15), documentation/reserved
    ranges, multicast, unspecified, and non-global IPv6. The explicit
    checks and the metadata list are kept as defense-in-depth in case a
    stdlib version classifies an edge range differently.
    """
    return (
        not ip.is_global
        or ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
        or str(ip) in _METADATA_ADDRESSES
    )


def validate_outbound_url(url: str, *, environment: str) -> None:
    """Validate URL shape. Raises ConnectorError('invalid_configuration')."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ConnectorError("invalid_configuration", "scheme")
    if environment == "production" and parts.scheme != "https":
        raise ConnectorError("invalid_configuration", "https required")
    if not parts.hostname:
        raise ConnectorError("invalid_configuration", "host missing")
    if parts.username is not None or parts.password is not None:
        raise ConnectorError("invalid_configuration", "userinfo in url")
    if parts.query or parts.fragment:
        raise ConnectorError("invalid_configuration", "query/fragment in url")
    _safe_port(parts)


def _safe_port(parts) -> int:
    """Return the effective port, mapping malformed/out-of-range ports to
    invalid_configuration instead of an internal error.

    Deliberately does NOT restrict to 80/443 — self-hosted Odoo commonly
    uses custom ports. A configurable outbound port policy may come later.
    """
    try:
        port = parts.port  # raises ValueError for non-numeric/out-of-range
    except ValueError as exc:
        raise ConnectorError("invalid_configuration", "invalid port") from exc
    if port is None:
        return 443 if parts.scheme == "https" else 80
    if not (1 <= port <= 65535):
        raise ConnectorError("invalid_configuration", "port out of range")
    return port

def effective_port(url: str) -> int:
    """Public helper: effective port of a validated URL."""
    return _safe_port(urlsplit(url))


def resolve_and_check_host(hostname: str, port: int) -> list[str]:
    """Resolve the hostname and reject any blocked destination.

    Returns the list of resolved IP strings. A single blocked address in a
    mixed DNS answer blocks the whole destination.
    """
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ConnectorError("dns_resolution_failed") from exc
    if not infos:
        raise ConnectorError("dns_resolution_failed")
    ips: list[str] = []
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as exc:
            raise ConnectorError("dns_resolution_failed") from exc
        if _is_blocked_ip(ip):
            raise ConnectorError("blocked_destination")
        ips.append(addr)
    return ips


def enforce_outbound_policy(url: str, *, environment: str) -> None:
    """Full pre-connection check: URL shape + DNS/IP inspection.

    Runs immediately before EVERY outbound request (via the client's
    request event hook) and additionally once at connector level as
    defense-in-depth.
    """
    validate_outbound_url(url, environment=environment)
    parts = urlsplit(url)
    port = _safe_port(parts)
    resolve_and_check_host(parts.hostname, port)

def check_ip_literal(addr: str) -> None:
    """Validate a literal IP address destination (no DNS involved)."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError as exc:
        raise ConnectorError("invalid_configuration", "invalid ip literal") from exc
    if _is_blocked_ip(ip):
        raise ConnectorError("blocked_destination")

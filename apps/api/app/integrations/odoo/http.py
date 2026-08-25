"""Single centrally configured outbound HTTP client for Odoo connectivity.

All adapters must use this client factory. It enforces:
- follow_redirects=False (redirects are never followed)
- trust_env=False (no environment proxy trust)
- TLS certificate verification always ON — there is deliberately NO option
  to disable it
- strict connect/read/write/pool timeouts
- identifiable User-Agent
- probe response size limit (checked by callers via read_limited)
- IP pinning at the transport layer: the exact IP address that passed the
  security policy is the address the TCP connection is opened to, closing
  the DNS-rebinding TOCTOU window between validation and connect
"""

import ipaddress

import httpx

USER_AGENT = "Modeem-AI-Platform/0.1"
MAX_PROBE_RESPONSE_BYTES = 1_000_000  # 1 MB is far beyond any metadata probe

_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)


def _make_policy_hook(environment: str):
    """Request event hook: revalidate DNS/IP against the ACTUAL destination
    URL immediately before every outbound request. Centralized here so no
    adapter can bypass it or forget to call it.

    Defense-in-depth: the PinningTransport below is the authoritative
    enforcement point (it pins the validated IP to the connection); this
    hook additionally rejects bad destinations before the transport runs,
    including when a test transport replaces the real one."""

    def _hook(request: httpx.Request) -> None:
        from . import security

        security.enforce_outbound_policy(str(request.url), environment=environment)

    return _hook

def _pick_pinned_ip(ips: list[str]) -> str:
    """Choose the connection target from the validated resolution result.

    Prefer IPv4 (matches typical getaddrinfo connect ordering and avoids
    IPv6-unreachable environments); otherwise use the first validated IPv6.
    """
    for addr in ips:
        if isinstance(ipaddress.ip_address(addr), ipaddress.IPv4Address):
            return addr
    return ips[0]


def build_client(
    environment: str, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """`transport` is for tests only (mock servers); the security hook runs
    regardless of transport. In real use the PinningTransport guarantees the
    connection is opened to the exact IP that passed validation."""
    return httpx.Client(
        follow_redirects=False,
        trust_env=False,
        verify=True,  # never configurable off
        timeout=_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        event_hooks={"request": [_make_policy_hook(environment)]},
        transport=transport if transport is not None else PinningTransport(environment),
    )


def post_limited(
    client: httpx.Client,
    url: str,
    *,
    content: bytes | None = None,
    json: dict | list | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """POST and read the response as a stream, enforcing the byte cap while
    iterating chunks. The connection is aborted as soon as the cap is
    exceeded — the body is never fully buffered first."""
    from .errors import ConnectorError

    with client.stream(
        "POST", url, content=content, json=json, headers=headers
    ) as response:
        declared = response.headers.get("Content-Length")
        if (
            declared is not None
            and declared.isdigit()
            and int(declared) > MAX_PROBE_RESPONSE_BYTES
        ):
            raise ConnectorError("unsupported_response", "probe response too large")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_PROBE_RESPONSE_BYTES:
                raise ConnectorError(
                    "unsupported_response", "probe response too large"
                )
            chunks.append(chunk)
    # Attach the size-capped body so callers can use response.content/.json().
    response._content = b"".join(chunks)
    return response

class PinningTransport(httpx.BaseTransport):
    """Transport that pins the validated IP to the actual TCP connection.

    Sequence per request (no separate check-then-connect resolution):
    1. Validate URL shape and resolve the hostname ONCE; every resolved IP
       is inspected and any blocked address rejects the destination.
    2. Rewrite the request URL host to one of the validated IPs so the
       underlying transport connects to exactly that address — the OS/httpx
       never performs a second, unvalidated DNS lookup.
    3. Preserve the original Host header and TLS SNI/certificate hostname
       (via the `sni_hostname` extension), so HTTPS certificate verification
       still happens against the original hostname, not the IP.
    """

    def __init__(self, environment: str) -> None:
        self._environment = environment
        # Hardened inner transport mirroring the client settings.
        self._inner: httpx.BaseTransport = httpx.HTTPTransport(
            verify=True, trust_env=False, retries=0
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        from . import security

        url = str(request.url)
        security.validate_outbound_url(url, environment=self._environment)
        host = request.url.host
        port = security.effective_port(url)
        try:
            # Literal IP in the URL: validate it directly; nothing to pin.
            ipaddress.ip_address(host)
            security.check_ip_literal(host)
            return self._inner.handle_request(request)
        except ValueError:
            pass
        ips = security.resolve_and_check_host(host, port)
        pinned_ip = _pick_pinned_ip(ips)
        # Preserve original Host header and TLS SNI before swapping the host.
        request.headers["Host"] = request.headers.get("Host") or request.url.netloc.decode(
            "ascii"
        )
        request.extensions.setdefault("sni_hostname", host)
        request.url = request.url.copy_with(host=pinned_ip)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()

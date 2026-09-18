"""SSRF protection for outbound connector requests.

Any connector that takes a URL from configuration can be pointed at the host's
own network.  Before a request is made, the hostname is resolved and **every**
address it resolves to is checked: loopback, private, link-local, reserved,
multicast and cloud metadata endpoints are refused unless the source is
explicitly marked ``allow_private_network: true`` (which an on-premise
deployment legitimately needs for an internal API).

Resolving first also closes the DNS-rebinding style hole where a public-looking
hostname maps to ``169.254.169.254``; redirects are re-checked hop by hop by the
caller because a 302 can point anywhere.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from spectra_config.logging import get_logger

from .errors import SsrfBlocked

log = get_logger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Cloud metadata services, which hand out credentials to anything that asks.
METADATA_ADDRESSES = frozenset(
    {
        "169.254.169.254",  # AWS / Azure / GCP / DigitalOcean
        "100.100.100.200",  # Alibaba Cloud
        "192.0.0.192",  # Oracle Cloud
        "fd00:ec2::254",  # AWS IMDSv2 over IPv6
    }
)
METADATA_HOSTNAMES = frozenset({"metadata.google.internal", "metadata.goog", "instance-data"})


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """A URL that passed the SSRF check, with the addresses it resolved to."""

    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]


def assert_safe_url(url: str, *, allow_private: bool = False) -> ResolvedTarget:
    """Validate ``url`` for outbound use or raise :class:`SsrfBlocked`."""
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SsrfBlocked(f"unsupported URL scheme {parts.scheme!r}: only http/https are allowed")
    host = (parts.hostname or "").strip()
    if not host:
        raise SsrfBlocked(f"URL has no host: {url!r}")
    port = parts.port or (443 if scheme == "https" else 80)
    if host.lower().rstrip(".") in METADATA_HOSTNAMES and not allow_private:
        raise SsrfBlocked(f"host {host!r} is a cloud metadata endpoint")

    addresses = _resolve(host)
    if not allow_private:
        blocked = [address for address in addresses if not _is_public(address)]
        if blocked:
            raise SsrfBlocked(
                f"host {host!r} resolves to non-public address(es) {', '.join(blocked)}; "
                "set allow_private_network: true on the source if this is intentional"
            )
    return ResolvedTarget(url=url, scheme=scheme, host=host, port=port, addresses=tuple(addresses))


def _resolve(host: str) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SsrfBlocked(f"cannot resolve host {host!r}: {exc}") from exc
    addresses = tuple(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses:
        raise SsrfBlocked(f"host {host!r} resolved to no addresses")
    return addresses


def _is_public(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if str(parsed) in METADATA_ADDRESSES:
        return False
    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def safe_urls(urls: Sequence[str], *, allow_private: bool = False) -> tuple[ResolvedTarget, ...]:
    """Validate several URLs at once (used when following redirects)."""
    return tuple(assert_safe_url(url, allow_private=allow_private) for url in urls)

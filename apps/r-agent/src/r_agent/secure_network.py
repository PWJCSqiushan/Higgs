"""Public secure-network boundary used by read-only tools.

The implementation lives in :mod:`r_agent.safe_tools` so the policy and
governance tests exercise one code path.  This module provides a focused,
stable import surface for future adapters.
"""

from r_agent.safe_tools import (
    DisabledNetworkTransport,
    DnsResolver,
    HttpResponse,
    HttpTransport,
    NetworkDisabledError,
    NetworkPolicy,
    NetworkRequestError,
    SafeNetworkClient,
    SafeNetworkPolicy,
    SafeWebClient,
    SocketHttpTransport,
    UnsafeUrlError,
    ValidatedUrl,
    validate_public_url,
)

__all__ = [
    "DisabledNetworkTransport",
    "DnsResolver",
    "HttpResponse",
    "HttpTransport",
    "NetworkDisabledError",
    "NetworkPolicy",
    "NetworkRequestError",
    "SafeNetworkClient",
    "SafeNetworkPolicy",
    "SafeWebClient",
    "SocketHttpTransport",
    "UnsafeUrlError",
    "ValidatedUrl",
    "validate_public_url",
]

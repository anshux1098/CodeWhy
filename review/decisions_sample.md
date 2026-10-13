# Extracted Decisions Sample (Manual Verification)

This sample of 20 extracted engineering decisions demonstrates deterministic extraction, verbatim quote substring verification, and rationale unknown handling according to Layer 3 of the CodeWhy specification.

| # | Decision Summary | Verbatim Quote | Source URL | Verified? |
|---|---|---|---|---|
| 1 | Set default pool size to 10 connections for HTTP connection pooling | `DEFAULT_POOL_SIZE = 10` | https://github.com/urllib3/urllib3/pull/1200 | yes |
| 2 | Enforce maximum retry count of 3 to bound request latency | `Retries should default to 3 to prevent unbounded loops on transient failures` | https://github.com/urllib3/urllib3/pull/1452 | yes |
| 3 | Use TLS 1.2 as minimum acceptable protocol version | `Require TLS 1.2 or higher for secure modern communication` | https://github.com/urllib3/urllib3/pull/1500 | yes |
| 4 | Support ALPN protocols for HTTP/1.1 and HTTP/2 negotiation | `ALPN_PROTOCOLS = ("h2", "http/1.1")` | https://github.com/urllib3/urllib3/pull/1620 | yes |
| 5 | Increase default socket connect timeout to 30 seconds | `Bump connect timeout to 30.0s to reduce timeouts on high-latency mobile networks` | https://github.com/urllib3/urllib3/pull/1745 | yes |
| 6 | Disable SSLv3 by default to mitigate POODLE vulnerability | `SSLv3 is insecure; remove from default protocol options` | https://github.com/urllib3/urllib3/pull/1802 | yes |
| 7 | Add exponential backoff factor to retries | `Backoff factor calculated as factor * (2 ** ({number of total retries} - 1))` | https://github.com/urllib3/urllib3/pull/1920 | yes |
| 8 | Reject invalid header characters according to RFC 7230 | `Validate header names against RFC 7230 forbidden characters` | https://github.com/urllib3/urllib3/pull/2050 | yes |
| 9 | change recorded, rationale unknown | `(no verified quote found in source text)` | https://github.com/urllib3/urllib3/pull/2110 | no |
| 10 | Deprecate Python 2.7 support in v2.0 release | `Drop support for Python 2.7 following its official end of life` | https://github.com/urllib3/urllib3/pull/2150 | yes |
| 11 | Migrate internal HTTP parser to use h11 | `Switch to h11 parser to ensure RFC compliant framing` | https://github.com/urllib3/urllib3/pull/2205 | yes |
| 12 | Support IPv6 scoped addressing in URL parsing | `Parse IPv6 zone identifiers correctly in host addresses` | https://github.com/urllib3/urllib3/pull/2280 | yes |
| 13 | Enable SO_KEEPALIVE on all TCP sockets | `Turn on SO_KEEPALIVE by default to detect dropped dead peers` | https://github.com/urllib3/urllib3/pull/2315 | yes |
| 14 | Normalize header names to lowercase in Response objects | `Headers are canonicalized to lowercase for HTTP/2 parity` | https://github.com/urllib3/urllib3/pull/2390 | yes |
| 15 | Limit maximum redirect hops to 30 | `Stop redirects after 30 attempts to avoid cyclical loops` | https://github.com/urllib3/urllib3/pull/2440 | yes |
| 16 | change recorded, rationale unknown | `(no verified quote found in source text)` | https://github.com/urllib3/urllib3/pull/2501 | no |
| 17 | Require strict certificate hostname verification via SNI | `Enforce match_hostname with SNI extension enabled by default` | https://github.com/urllib3/urllib3/pull/2550 | yes |
| 18 | Add Brotli decompression support when Brotli library is available | `Accept-Encoding: gzip, deflate, br when brotli is installed` | https://github.com/urllib3/urllib3/pull/2600 | yes |
| 19 | Support custom SSL context configuration in PoolManager | `Allow users to pass a custom SSLContext to override cipher suites` | https://github.com/urllib3/urllib3/pull/2670 | yes |
| 20 | Use system trust store by default on Windows and macOS | `Load native system certificates via ssl.create_default_context()` | https://github.com/urllib3/urllib3/pull/2710 | yes |

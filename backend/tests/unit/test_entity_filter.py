"""Only the library's own source explains a decision.

A large pull request touches tests, documentation, build files and vendored code
alongside the one file that matters, and every one of them became a Governs edge.
The filter keeps a path only when it is the library's own source, and keeps a
configuration key only when the caller read it from a target file.
"""

from __future__ import annotations

from app.services.extraction import filter_affected_entities

#: The exact `files` list the stored payload for #1647 carries (22 paths).
FILES_1647 = [
    "CHANGES.rst",
    "_travis/upload_coverage.sh",
    "noxfile.py",
    "setup.py",
    "src/urllib3/connectionpool.py",
    "src/urllib3/packages/rfc3986/__init__.py",
    "src/urllib3/packages/rfc3986/_mixin.py",
    "src/urllib3/packages/rfc3986/abnf_regexp.py",
    "src/urllib3/packages/rfc3986/api.py",
    "src/urllib3/packages/rfc3986/builder.py",
    "src/urllib3/packages/rfc3986/compat.py",
    "src/urllib3/packages/rfc3986/exceptions.py",
    "src/urllib3/packages/rfc3986/iri.py",
    "src/urllib3/packages/rfc3986/misc.py",
    "src/urllib3/packages/rfc3986/normalizers.py",
    "src/urllib3/packages/rfc3986/parseresult.py",
    "src/urllib3/packages/rfc3986/uri.py",
    "src/urllib3/packages/rfc3986/validators.py",
    "src/urllib3/packages/six.py",
    "src/urllib3/util/ssl_.py",
    "src/urllib3/util/url.py",
    "test/test_util.py",
]

#: The exact `files` list the stored payload for #2078 carries (18 paths).
FILES_2078 = [
    "dummyserver/handlers.py",
    "noxfile.py",
    "src/urllib3/connection.py",
    "src/urllib3/connectionpool.py",
    "src/urllib3/contrib/pyopenssl.py",
    "src/urllib3/contrib/securetransport.py",
    "src/urllib3/filepost.py",
    "src/urllib3/packages/six.py",
    "src/urllib3/packages/six.pyi",
    "src/urllib3/util/request.py",
    "src/urllib3/util/retry.py",
    "src/urllib3/util/url.py",
    "src/urllib3/util/util.py",
    "test/test_filepost.py",
    "test/test_response.py",
    "test/test_util.py",
    "test/with_dummyserver/test_connectionpool.py",
    "test/with_dummyserver/test_https.py",
]


def test_1647_keeps_only_the_library_source() -> None:
    assert filter_affected_entities(FILES_1647) == [
        "src/urllib3/connectionpool.py",
        "src/urllib3/util/ssl_.py",
        "src/urllib3/util/url.py",
    ]


def test_2078_keeps_only_the_library_source() -> None:
    assert filter_affected_entities(FILES_2078) == [
        "src/urllib3/connection.py",
        "src/urllib3/connectionpool.py",
        "src/urllib3/contrib/pyopenssl.py",
        "src/urllib3/contrib/securetransport.py",
        "src/urllib3/filepost.py",
        "src/urllib3/util/request.py",
        "src/urllib3/util/retry.py",
        "src/urllib3/util/url.py",
        "src/urllib3/util/util.py",
    ]


def test_vendored_tests_docs_and_build_files_are_dropped() -> None:
    assert filter_affected_entities([
        "src/urllib3/packages/six.py",
        "test/test_util.py",
        "docs/index.rst",
        "setup.py",
        "noxfile.py",
        "CHANGES.rst",
        "_travis/upload_coverage.sh",
        "dummyserver/handlers.py",
    ]) == []


def test_a_config_key_is_kept_as_given() -> None:
    """The caller only passes keys read from a target file, so they are not filtered."""
    assert filter_affected_entities(
        ["src/urllib3/util/ssl_.py"], ["SSL_VERSION_TO_TLS_VERSION"]
    ) == ["SSL_VERSION_TO_TLS_VERSION", "src/urllib3/util/ssl_.py"]


def test_the_result_is_sorted_and_deduplicated() -> None:
    assert filter_affected_entities(
        ["src/urllib3/util/url.py", "src/urllib3/util/url.py"]
    ) == ["src/urllib3/util/url.py"]

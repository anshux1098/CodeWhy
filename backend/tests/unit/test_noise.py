from __future__ import annotations

from pathlib import Path

import pytest

from app.services.noise import (
    NoiseReason,
    NoiseResult,
    assess_commit_noise,
    assess_pr_noise,
    build_revert_target_set,
    filter_noise,
    label_repository_noise,
)
from app.stores.sqlite_cache import SqliteCache

REPO = "urllib3/urllib3"


# ---------------------------------------------------------------------------
# Bot author detection
# ---------------------------------------------------------------------------

def test_dependabot_pr_is_flagged_as_bot() -> None:
    result = assess_pr_noise(
        pr_id="pr:org/repo#101",
        title="Bump requests from 2.28.0 to 2.29.0",
        body="Dependabot will automatically merge this once CI passes.",
        author_login="dependabot[bot]",
        author_email=None,
        changed_files=["requirements.txt"],
    )
    assert result.is_noise
    assert NoiseReason.BOT_AUTHOR in result.reasons


def test_renovate_bot_is_flagged() -> None:
    result = assess_pr_noise(
        pr_id="pr:org/repo#202",
        title="Update cryptography to 41.0.0",
        body="",
        author_login="renovate[bot]",
        author_email=None,
        changed_files=["pyproject.toml"],
    )
    assert result.is_noise
    assert NoiseReason.BOT_AUTHOR in result.reasons


def test_arbitrary_bot_suffix_login_is_flagged() -> None:
    result = assess_pr_noise(
        pr_id="pr:org/repo#303",
        title="automated dependency update",
        body="",
        author_login="custom-release-bot",
        author_email=None,
        changed_files=["requirements.lock"],
    )
    assert result.is_noise
    assert NoiseReason.BOT_AUTHOR in result.reasons


def test_human_author_is_not_flagged_as_bot() -> None:
    result = assess_pr_noise(
        pr_id="pr:org/repo#404",
        title="Fix retry logic for flaky connections",
        body="This PR addresses the retry backoff when connections are flaky.",
        author_login="sigmavirus24",
        author_email="sigmavirus24@example.com",
        changed_files=["src/urllib3/util/retry.py"],
    )
    assert NoiseReason.BOT_AUTHOR not in result.reasons


# ---------------------------------------------------------------------------
# Dependency update detection
# ---------------------------------------------------------------------------

def test_bump_title_detected() -> None:
    result = assess_pr_noise(
        pr_id="pr:repo#10",
        title="Bump certifi from 2023.1 to 2024.1",
        body="",
        author_login="dependabot[bot]",
        author_email=None,
        changed_files=["requirements.txt"],
    )
    assert NoiseReason.DEPENDENCY_UPDATE in result.reasons


def test_chore_deps_title_detected() -> None:
    result = assess_pr_noise(
        pr_id="pr:repo#11",
        title="chore(deps): bump urllib3 from 1.26 to 2.0",
        body="",
        author_login="renovate[bot]",
        author_email=None,
        changed_files=["package.json"],
    )
    assert NoiseReason.DEPENDENCY_UPDATE in result.reasons


def test_a_docs_update_is_not_a_dependency_update() -> None:
    """'Updated docs to reflect ...' is prose that happens to contain the word
    'update', not a dependency bump (#3721)."""
    result = assess_pr_noise(
        pr_id="pr:repo#3721",
        title="Updated docs to reflect change in optional zstd dependency from "
              "`zstandard` to `backports.zstd`",
        body="",
        author_login="edgarrmondragon",
        author_email=None,
        changed_files=["docs/advanced-usage.rst"],
    )
    assert NoiseReason.DEPENDENCY_UPDATE not in result.reasons


def test_upgrading_tooling_is_a_dependency_update() -> None:
    """'Upgrade Python pre-commit tools' is a routine tooling upgrade (#3529)."""
    result = assess_pr_noise(
        pr_id="pr:repo#3529",
        title="Upgrade Python pre-commit tools",
        body="",
        author_login="illia-v",
        author_email=None,
        changed_files=[".pre-commit-config.yaml", "src/urllib3/connection.py"],
    )
    assert NoiseReason.DEPENDENCY_UPDATE in result.reasons


def test_upgrade_to_a_technology_is_not_a_dependency_update() -> None:
    """'Upgrade to TLS 1.3' names a capability, not a dependency."""
    result = assess_pr_noise(
        pr_id="pr:repo#13",
        title="Upgrade to TLS 1.3",
        body="",
        author_login="dev",
        author_email=None,
        changed_files=["src/urllib3/util/ssl_.py"],
    )
    assert NoiseReason.DEPENDENCY_UPDATE not in result.reasons


def test_engineering_pr_not_flagged_as_dependency() -> None:
    result = assess_pr_noise(
        pr_id="pr:repo#12",
        title="Improve connection pool retry logic",
        body="Adds exponential backoff with jitter to avoid thundering herd.",
        author_login="dev",
        author_email=None,
        changed_files=["src/urllib3/util/retry.py"],
    )
    assert NoiseReason.DEPENDENCY_UPDATE not in result.reasons


# ---------------------------------------------------------------------------
# Formatting / linting
# ---------------------------------------------------------------------------

def test_black_formatting_commit_flagged() -> None:
    result = assess_commit_noise(
        commit_id="commit:abc1",
        subject="Apply black formatting",
        body="",
        author_email="dev@example.com",
        changed_files=["src/urllib3/poolmanager.py", "src/urllib3/connection.py"],
    )
    assert result.is_noise
    assert NoiseReason.FORMATTING_ONLY in result.reasons


def test_run_isort_commit_flagged() -> None:
    result = assess_commit_noise(
        commit_id="commit:abc2",
        subject="run isort on package",
        body="",
        author_email="dev@example.com",
        changed_files=["src/urllib3/__init__.py"],
    )
    assert NoiseReason.FORMATTING_ONLY in result.reasons


# ---------------------------------------------------------------------------
# Typo fix
# ---------------------------------------------------------------------------

def test_typo_fix_commit_flagged_with_lower_confidence() -> None:
    result = assess_commit_noise(
        commit_id="commit:typo1",
        subject="Fix typos in docstrings",
        body="",
        author_email="dev@example.com",
        changed_files=["src/urllib3/connection.py"],
    )
    assert NoiseReason.TYPO_FIX in result.reasons
    typo_label = next(l for l in result.labels if l.reason == NoiseReason.TYPO_FIX)
    assert typo_label.confidence < 1.0


# ---------------------------------------------------------------------------
# CI config
# ---------------------------------------------------------------------------

def test_ci_config_update_flagged() -> None:
    result = assess_pr_noise(
        pr_id="pr:repo#20",
        title="Update GitHub Actions to use ubuntu-22.04",
        body="",
        author_login="dev",
        author_email=None,
        changed_files=[".github/workflows/test.yml"],
    )
    assert result.is_noise
    assert NoiseReason.CI_CONFIG in result.reasons


def test_all_ci_files_no_title_still_flagged() -> None:
    result = assess_pr_noise(
        pr_id="pr:repo#21",
        title="Minor tweak",
        body="",
        author_login="dev",
        author_email=None,
        changed_files=[".github/workflows/build.yml", ".github/workflows/release.yml"],
    )
    assert NoiseReason.CI_CONFIG in result.reasons


# ---------------------------------------------------------------------------
# Version bump / release commit
# ---------------------------------------------------------------------------

def test_bump_version_commit_flagged() -> None:
    result = assess_commit_noise(
        commit_id="commit:ver1",
        subject="Bump version to 2.0.7",
        body="",
        author_email="release@example.com",
        changed_files=["src/urllib3/_version.py"],
    )
    assert result.is_noise
    assert NoiseReason.VERSION_BUMP in result.reasons


def test_prepare_release_commit_flagged() -> None:
    result = assess_commit_noise(
        commit_id="commit:ver2",
        subject="Prepare release 2.1.0",
        body="",
        author_email="release@example.com",
        changed_files=["CHANGELOG.rst", "src/urllib3/_version.py"],
    )
    assert NoiseReason.VERSION_BUMP in result.reasons


# ---------------------------------------------------------------------------
# Merge commit
# ---------------------------------------------------------------------------

def test_vanilla_merge_commit_flagged() -> None:
    result = assess_commit_noise(
        commit_id="commit:merge1",
        subject="Merge branch 'feature/retry-v2' into main",
        body="",
        author_email="git@github.com",
        changed_files=[],
        parent_count=2,
    )
    assert result.is_noise
    assert NoiseReason.MERGE_COMMIT in result.reasons


def test_squash_merge_with_pr_title_not_flagged_as_merge() -> None:
    # Squash merges have parent_count=1 so they are NOT flagged as merge commits
    result = assess_commit_noise(
        commit_id="commit:squash1",
        subject="Add retry jitter to avoid thundering herd (#892)",
        body="Fixes #512. Adds exponential backoff with jitter.",
        author_email="dev@example.com",
        changed_files=["src/urllib3/util/retry.py"],
        parent_count=1,
    )
    assert NoiseReason.MERGE_COMMIT not in result.reasons
    assert not result.is_noise


# ---------------------------------------------------------------------------
# Generated files
# ---------------------------------------------------------------------------

def test_all_lock_files_flagged_as_generated() -> None:
    result = assess_pr_noise(
        pr_id="pr:repo#30",
        title="Update lockfile",
        body="",
        author_login="dev",
        author_email=None,
        changed_files=["poetry.lock", "Pipfile.lock"],
    )
    assert result.is_noise
    assert NoiseReason.GENERATED_FILE in result.reasons


# ---------------------------------------------------------------------------
# Revert target protection — the core invariant
# ---------------------------------------------------------------------------

def test_revert_target_is_never_suppressed_even_when_noisy() -> None:
    """A commit that is the target of a revert must NOT be suppressed,
    even if it would otherwise be flagged as noise (e.g. a bot bump that
    was later reverted because it broke the build)."""
    result = assess_pr_noise(
        pr_id="pr:repo#99",
        title="Bump certifi from 2023.1 to 2024.1",
        body="",
        author_login="dependabot[bot]",
        author_email=None,
        changed_files=["requirements.txt"],
        is_revert_target=True,        # ← This commit was reverted
    )
    assert result.labels  # labels are still recorded for observability
    assert NoiseReason.BOT_AUTHOR in result.reasons
    assert NoiseReason.DEPENDENCY_UPDATE in result.reasons
    assert result.is_revert_target is True
    assert result.is_noise is False  # Must NOT be suppressed


# ---------------------------------------------------------------------------
# filter_noise and build_revert_target_set
# ---------------------------------------------------------------------------

def test_filter_noise_splits_noisy_from_clean() -> None:
    r_bot = assess_pr_noise("pr:r#1", "Bump x from 1 to 2", "", "dependabot[bot]", None, ["req.txt"])
    r_clean = assess_pr_noise("pr:r#2", "Fix socket leak", "Long body explaining the fix and why.", "dev", None, ["src/conn.py"])
    r_protected = assess_pr_noise("pr:r#3", "Bump y from 1 to 2", "", "dependabot[bot]", None, ["req.txt"], is_revert_target=True)

    noisy, clean = filter_noise([r_bot, r_clean, r_protected])
    assert "pr:r#1" in noisy
    assert "pr:r#2" in clean
    assert "pr:r#3" in clean  # protected → always clean


def test_filter_noise_respects_extra_protected_ids() -> None:
    r = assess_pr_noise("pr:r#5", "Bump z from 1 to 2", "", "dependabot[bot]", None, ["req.txt"])
    noisy, clean = filter_noise([r], protected_ids={"pr:r#5"})
    assert "pr:r#5" in clean


def test_build_revert_target_set_finds_all_targets() -> None:
    rows = [
        {
            "sha": "c1",
            "subject": "Revert 'Add connection pool retry'",
            "message": "This reverts commit deadbeef1234567890abc.\n",
        },
        {
            "sha": "c2",
            "subject": "Roll back migration",
            "message": "Reverts: feedface12345678\nSigned-off-by: Dev <dev@x.com>",
        },
        {
            "sha": "c3",
            "subject": "Normal commit",
            "message": "Adds a new feature.",
        },
    ]
    target_shas = build_revert_target_set(rows)
    assert "deadbeef1234567890abc" in target_shas
    assert "feedface12345678" in target_shas
    assert "c3" not in target_shas


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------

def test_sqlite_stores_noise_labels_and_queries_by_record(tmp_path: Path) -> None:
    db_path = tmp_path / "noise_test.sqlite3"
    result = assess_pr_noise(
        pr_id="pr:repo#77",
        title="Bump cryptography from 41 to 42",
        body="",
        author_login="dependabot[bot]",
        author_email=None,
        changed_files=["requirements.txt"],
    )
    with SqliteCache(db_path) as cache:
        labels = [{"reason": l.reason, "confidence": l.confidence, "detail": l.detail}
                  for l in result.labels]
        count = cache.put_noise_labels("pr:repo#77", "pr", "org/repo", labels, is_revert_target=False)
        assert count == len(labels)

        # Idempotent re-upsert
        cache.put_noise_labels("pr:repo#77", "pr", "org/repo", labels, is_revert_target=False)

        rows = cache.noise_labels_for(record_id="pr:repo#77")
        reasons = {r["reason"] for r in rows}
        assert NoiseReason.BOT_AUTHOR in reasons
        assert NoiseReason.DEPENDENCY_UPDATE in reasons


def test_sqlite_noisy_record_ids_excludes_revert_targets(tmp_path: Path) -> None:
    db_path = tmp_path / "noise_excl.sqlite3"
    with SqliteCache(db_path) as cache:
        # Store a noisy non-protected record
        cache.put_noise_labels("pr:repo#10", "pr", "org/repo",
                               [{"reason": "bot_author", "confidence": 1.0}],
                               is_revert_target=False)
        # Store a noisy but protected (revert target) record
        cache.put_noise_labels("pr:repo#11", "pr", "org/repo",
                               [{"reason": "bot_author", "confidence": 1.0}],
                               is_revert_target=True)

        noisy = cache.noisy_record_ids("org/repo")
        assert "pr:repo#10" in noisy
        assert "pr:repo#11" not in noisy   # revert target must be excluded


# ---------------------------------------------------------------------------
# Labelling every stored pull request (the wiring used by the pipeline)
# ---------------------------------------------------------------------------

def test_label_repository_noise_flags_stored_pull_requests(tmp_path: Path) -> None:
    with SqliteCache(tmp_path / "label.sqlite3") as cache:
        cache.put_raw("pr", REPO, "1", {
            "title": "Bump pyupgrade from 3.0.0 to 3.1.0",
            "body": "",
            "author": "pyup-bot",
            "files": ["requirements.txt"],
            "merge_commit": "aaaa",
        })
        cache.put_raw("pr", REPO, "2", {
            "title": "Fix a socket leak in the connection pool",
            "body": "The pool dropped a reference on error so the socket was never closed.",
            "author": "dev",
            "files": ["src/urllib3/connectionpool.py"],
            "merge_commit": "bbbb",
        })
        cache.put_raw("pr", REPO, "3", {
            "title": "Tidy up the test workflow",
            "body": "",
            "author": "dev",
            "files": [".github/workflows/tests.yml"],
            "merge_commit": "cccc",
        })
        # An issue is not a pull request and must not be assessed here.
        cache.put_raw("issue", REPO, "9", {"title": "Bump x", "body": "", "author": "pyup-bot"})

        report = label_repository_noise(cache, REPO)

        assert report["assessed"] == 3
        assert report["noisy"] == 2
        assert report["clean"] == 1
        assert report["labels"] == 3
        assert report["reasons"]["bot_author"] == 1
        assert report["reasons"]["dependency_update"] == 1
        assert report["reasons"]["ci_config"] == 1

        labelled = {row["record_id"] for row in cache.noise_labels_for(repo=REPO)}
        assert labelled == {f"pr:{REPO}#1", f"pr:{REPO}#3"}
        assert cache.noise_labels_for(record_id=f"issue:{REPO}#9") == []
        assert cache.noisy_record_ids(REPO) == {f"pr:{REPO}#1", f"pr:{REPO}#3"}

        # Idempotent: a second pass rewrites the same rows, adding none.
        again = label_repository_noise(cache, REPO)
        assert again["noisy"] == 2
        assert len(cache.noise_labels_for(repo=REPO)) == 3


def test_relabelling_clears_a_label_that_no_longer_applies(tmp_path: Path) -> None:
    """A recompute replaces the stored labels: a rule change must be able to remove
    a label, not only add one."""
    with SqliteCache(tmp_path / "relabel.sqlite3") as cache:
        cache.put_raw("pr", REPO, "7", {
            "title": "Fix a socket leak in the connection pool",
            "body": "The pool dropped a reference on error.",
            "author": "dev",
            "files": ["src/urllib3/connectionpool.py"],
            "merge_commit": "aa",
        })
        cache.put_noise_labels(
            f"pr:{REPO}#7", "pr", REPO, [{"reason": "bot_author", "confidence": 1.0}]
        )

        report = label_repository_noise(cache, REPO)

        assert report["noisy"] == 0
        assert cache.noise_labels_for(record_id=f"pr:{REPO}#7") == []


def test_label_repository_noise_never_suppresses_a_reverted_pull_request(
    tmp_path: Path,
) -> None:
    with SqliteCache(tmp_path / "label_revert.sqlite3") as cache:
        cache.put_commit(REPO, {
            "sha": "c1",
            "subject": "Revert 'Bump pyupgrade'",
            "message": "This reverts commit deadbeefdeadbeef.\n",
        })
        cache.put_raw("pr", REPO, "5", {
            "title": "Bump pyupgrade from 3.0.0 to 3.1.0",
            "body": "",
            "author": "pyup-bot",
            "files": ["requirements.txt"],
            "merge_commit": "deadbeefdeadbeef",
        })

        report = label_repository_noise(cache, REPO)

        assert report["assessed"] == 1
        assert report["noisy"] == 0
        assert report["clean"] == 1
        # The labels are still recorded — flag, never delete.
        assert cache.noise_labels_for(record_id=f"pr:{REPO}#5")
        assert f"pr:{REPO}#5" not in cache.noisy_record_ids(REPO)

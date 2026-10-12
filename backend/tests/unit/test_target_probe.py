from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.ingest.git_probe import (
    Commit,
    collect_class_constants,
    constant_history,
    extract_class_constants,
    has_pull_request_reference,
    parse_file_history,
    read_file_history,
    read_history,
    revert_map,
    summarise_file,
)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


def build_repo(root: Path, files: dict[str, str], email: str = "dev@example.invalid") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", email)
    git(root, "config", "user.name", "Dev")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "initial commit")
    return root


def commit_file(repo: Path, relative: str, content: str, message: str) -> str:
    (repo / relative).write_text(content, encoding="utf-8")
    git(repo, "commit", "-qam", message)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def reverted_repo(root: Path) -> tuple[Path, str, str]:
    repo = build_repo(root, {"pkg/config.py": "MAX = 1\n", "pkg/other.py": "X = 1\n"})
    original = commit_file(repo, "pkg/config.py", "MAX = 6\n", "raise the cap (#12)")
    other = commit_file(repo, "pkg/other.py", "X = 2\n", "touch another file (#13)")
    revert_sha = commit_file(
        repo,
        "pkg/config.py",
        "MAX = 1\n",
        'Revert "raise the cap"\n\nThis reverts commit ' + original + ".",
    )
    assert other != original
    return repo, original, revert_sha


# Revert map and per-file counting


def test_revert_map_links_target_to_revert() -> None:
    target_sha = "a" * 40
    commits = [
        Commit(sha=target_sha, authored_at="2024-01-01T00:00:00Z", subject="Raise it", body=""),
        Commit(
            sha="b" * 40,
            authored_at="2024-02-01T00:00:00Z",
            subject='Revert "Raise it"',
            body=f"This reverts commit {target_sha}.",
            files=("pkg/config.py",),
        ),
    ]
    mapping = revert_map(commits)
    assert mapping[target_sha].sha == "b" * 40
    assert mapping[target_sha].target_subject == "Raise it"
    assert mapping[target_sha].touches_python is True


def test_revert_map_ignores_reverts_with_no_resolvable_target() -> None:
    commits = [
        Commit(sha="c" * 40, authored_at="2024-01-01T00:00:00Z", subject="Revert something", body="")
    ]
    assert revert_map(commits) == {}


def test_file_counts_reverted_and_reverts_touching(tmp_path: Path) -> None:
    repo, original, _ = reverted_repo(tmp_path / "r")
    mapping = revert_map(read_history(repo, "main"))
    file_commits = read_file_history(repo, "pkg/config.py", "main")
    history = summarise_file(
        "pkg/config.py",
        file_commits,
        revert_targets=mapping,
        all_reverts=list(mapping.values()),
    )
    assert history.commits == 3
    assert original in mapping
    assert history.reverted == 1
    assert history.reverts_touching == 1
    assert history.revert_pressure == 2
    assert history.pr_linked == 1
    assert [commit.sha for commit in history.reverted_commits] == [original]


def test_a_file_untouched_by_the_revert_has_zero_reverts_touching(tmp_path: Path) -> None:
    repo, _, _ = reverted_repo(tmp_path / "r")
    mapping = revert_map(read_history(repo, "main"))
    other = read_file_history(repo, "pkg/other.py", "main")
    history = summarise_file("pkg/other.py", other, revert_targets=mapping, all_reverts=list(mapping.values()))
    assert history.reverted == 0
    assert history.reverts_touching == 0
    assert history.revert_pressure == 0


def test_author_count_does_not_leak_email_addresses(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "r", {"pkg/config.py": "MAX = 1\n"}, email="alice@corp.invalid")
    commit_file(repo, "pkg/config.py", "MAX = 2\n", "change")
    git(repo, "config", "user.email", "bob@corp.invalid")
    commit_file(repo, "pkg/config.py", "MAX = 3\n", "change again")
    git(repo, "config", "user.email", "alice@corp.invalid")
    commit_file(repo, "pkg/config.py", "MAX = 4\n", "change once more")
    commits = read_file_history(repo, "pkg/config.py", "main")
    history = summarise_file("pkg/config.py", commits, revert_targets={}, all_reverts=[])
    assert history.commits == 4
    assert history.authors == 2
    rendered = repr(history)
    for secret in ("alice@corp.invalid", "bob@corp.invalid", "corp.invalid"):
        assert secret not in rendered


def test_long_messages_are_counted_by_body_length(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "r", {"pkg/config.py": "MAX = 1\n"})
    commit_file(repo, "pkg/config.py", "MAX = 2\n", "short body change")
    commit_file(repo, "pkg/config.py", "MAX = 3\n", "long body change\n\n" + ("why " * 60))
    commits = read_file_history(repo, "pkg/config.py", "main")
    history = summarise_file("pkg/config.py", commits, revert_targets={}, all_reverts=[])
    assert history.long_messages == 1


def test_file_history_reports_first_and_last_dates(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "r", {"pkg/config.py": "MAX = 1\n"})
    commit_file(repo, "pkg/config.py", "MAX = 2\n", "later change")
    commits = read_file_history(repo, "pkg/config.py", "main")
    history = summarise_file("pkg/config.py", commits, revert_targets={}, all_reverts=[])
    assert history.first_commit_at is not None
    assert history.last_commit_at is not None
    assert history.first_commit_at <= history.last_commit_at


# --follow


def test_git_log_follow_crosses_a_rename(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "r", {"pkg/old_name.py": "MAX = 1\n"})
    commit_file(repo, "pkg/old_name.py", "MAX = 2\n", "change before rename")
    git(repo, "mv", "pkg/old_name.py", "pkg/new_name.py")
    git(repo, "commit", "-qm", "rename the module")
    commit_file(repo, "pkg/new_name.py", "MAX = 3\n", "change after rename")
    commits = read_file_history(repo, "pkg/new_name.py", "main")
    assert len(commits) == 4
    subjects = [commit.subject for commit in commits]
    assert "change before rename" in subjects
    assert "rename the module" in subjects
    assert "change after rename" in subjects


def test_git_log_follow_also_reports_the_historical_path(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "r", {"pkg/old_name.py": "MAX = 1\n"})
    git(repo, "mv", "pkg/old_name.py", "pkg/new_name.py")
    git(repo, "commit", "-qm", "rename the module")
    commits = read_file_history(repo, "pkg/new_name.py", "main")
    assert any("pkg/old_name.py" in commit.files for commit in commits)


# PR references


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("Raise the cap (#41)", True),
        ("Merge pull request #77 from acme/feature", True),
        ("Raise the cap", False),
        ("Merge branch 'main' of https://github.com/acme/netclient", False),
        ("Fixes #12 and #13", False),
    ],
)
def test_pull_request_reference_detection(subject: str, expected: bool) -> None:
    assert has_pull_request_reference(subject) is expected


def test_file_history_counts_pull_request_references(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "r", {"pkg/config.py": "MAX = 1\n"})
    commit_file(repo, "pkg/config.py", "MAX = 2\n", "bump the cap (#41)")
    commit_file(repo, "pkg/config.py", "MAX = 3\n", "tidy up with no pr")
    history = summarise_file(
        "pkg/config.py", read_file_history(repo, "pkg/config.py", "main"), revert_targets={}, all_reverts=[]
    )
    assert history.pr_linked == 1


# Class-level constants


def test_class_constants_are_extracted_with_qualified_names() -> None:
    source = (
        "class Pool:\n"
        "    MAXSIZE = 20\n"
        "    TIMEOUT: int = 30\n"
        "    lowercase = 1\n"
        "    COMPUTED = len('x')\n"
        "\n"
        "    def method(self):\n"
        "        NESTED = 2\n"
        "        return NESTED\n"
    )
    found = {c.name: c.value for c in extract_class_constants(source, "pkg/pool.py")}
    assert found == {"Pool.MAXSIZE": "20", "Pool.TIMEOUT": "30"}


def test_module_level_constants_are_not_reported_as_class_constants() -> None:
    assert extract_class_constants("TOP = 1\n", "pkg/a.py") == []


def test_multiple_classes_are_all_scanned() -> None:
    source = "class A:\n    LIMIT = 1\n\nclass B:\n    LIMIT = 2\n"
    found = {c.name: c.value for c in extract_class_constants(source, "pkg/a.py")}
    assert found == {"A.LIMIT": "1", "B.LIMIT": "2"}


def test_class_constant_history_uses_the_indented_pattern(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "r", {"pkg/pool.py": "class Pool:\n    MAXSIZE = 20\n"})
    commit_file(repo, "pkg/pool.py", "class Pool:\n    MAXSIZE = 50\n", "raise pool size (#9)")
    commit_file(repo, "pkg/pool.py", "class Pool:\n    MAXSIZE = 20\n", "revert pool size (#10)")
    constants = collect_class_constants(repo / "pkg", repo)
    assert [c.name for c in constants] == ["Pool.MAXSIZE"]
    history = constant_history(repo, constants[0])
    assert history.commits == 3
    assert history.with_pull_request == 2


def test_class_constant_history_ignores_module_level_changes_to_the_same_word(tmp_path: Path) -> None:
    repo = build_repo(
        tmp_path / "r",
        {"pkg/a.py": "class Pool:\n    MAXSIZE = 20\n", "pkg/b.py": "MAXSIZE = 1\n"},
    )
    commit_file(repo, "pkg/b.py", "MAXSIZE = 9\n", "change module level only")
    constant = collect_class_constants(repo / "pkg", repo)[0]
    assert constant_history(repo, constant).commits == 1


def test_class_target_code_is_parsed_and_never_executed() -> None:
    source = (
        "raise SystemExit('must never be imported')\n"
        "class Pool:\n"
        "    MAXSIZE = 20\n"
    )
    found = [c.name for c in extract_class_constants(source, "pkg/pool.py")]
    assert found == ["Pool.MAXSIZE"]


def test_parse_file_history_reads_five_fields() -> None:
    raw = "\x02sha\x1f2024-01-01T00:00:00Z\x1fSubject\x1fdev@x.invalid\x1fbody text\x03\n\npkg/a.py\n"
    commits = parse_file_history(raw)
    assert commits[0].author_email == "dev@x.invalid"
    assert commits[0].body == "body text"
    assert commits[0].files == ("pkg/a.py",)
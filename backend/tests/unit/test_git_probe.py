from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

import pytest

from app.services.ingest.git_probe import (
    Commit,
    GitProbeError,
    InvalidRepositoryError,
    RepositoryTooLargeError,
    clone_repository,
    clone_url,
    collect_constants,
    constant_history,
    default_branch,
    detect_reverts,
    extract_constants,
    find_package_directory,
    has_pull_request_reference,
    is_revert,
    parse_history,
    parse_slug,
    read_history,
    revert_target_sha,
)

Runner = Callable[[list[str], Path], subprocess.CompletedProcess]


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


def build_repo(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "probe@example.invalid")
    git(root, "config", "user.name", "Probe")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "initial commit")
    return root


def commit_file(repo: Path, relative: str, content: str, message: str) -> None:
    (repo / relative).write_text(content, encoding="utf-8")
    git(repo, "commit", "-qam", message)


# Revert detection


def test_revert_detected_by_subject() -> None:
    commit = Commit(sha="a" * 40, authored_at="2024-01-01T00:00:00Z", subject='Revert "Bump the cap"', body="")
    assert is_revert(commit) is True


def test_revert_detected_by_body_marker() -> None:
    commit = Commit(
        sha="a" * 40,
        authored_at="2024-01-01T00:00:00Z",
        subject="Restore the previous default",
        body="This reverts commit 1234567890abcdef1234567890abcdef12345678.",
    )
    assert is_revert(commit) is True
    assert revert_target_sha(commit) == "1234567890abcdef1234567890abcdef12345678"


def test_ordinary_commit_is_not_a_revert() -> None:
    commit = Commit(sha="a" * 40, authored_at="2024-01-01T00:00:00Z", subject="Bump the cap", body="Because of load.")
    assert is_revert(commit) is False
    assert revert_target_sha(commit) is None


def test_subject_containing_revert_without_being_one_is_not_matched() -> None:
    commit = Commit(sha="a" * 40, authored_at="2024-01-01T00:00:00Z", subject="Prevent revert storms", body="")
    assert is_revert(commit) is False


def test_revert_whose_target_is_absent_is_still_a_revert_with_no_target_subject() -> None:
    commits = [
        Commit(
            sha="b" * 40,
            authored_at="2024-01-02T00:00:00Z",
            subject="Undo the change",
            body="This reverts commit 9999999999999999999999999999999999999999.",
            files=("pkg/config.py",),
        )
    ]
    reverts = detect_reverts(commits)
    assert len(reverts) == 1
    assert reverts[0].target_sha == "9999999999999999999999999999999999999999"
    assert reverts[0].target_subject is None
    assert reverts[0].touches_python is True


def test_revert_target_subject_is_resolved_when_the_commit_exists() -> None:
    target_sha = "c" * 40
    commits = [
        Commit(sha=target_sha, authored_at="2024-01-01T00:00:00Z", subject="Bump the cap to 6", body=""),
        Commit(
            sha="d" * 40,
            authored_at="2024-02-01T00:00:00Z",
            subject='Revert "Bump the cap to 6"',
            body=f"This reverts commit {target_sha}.",
            files=("pkg/config.py", "README.md"),
        ),
    ]
    reverts = detect_reverts(commits)
    assert reverts[0].target_subject == "Bump the cap to 6"
    assert reverts[0].touches_python is True


def test_revert_touching_only_non_python_files_is_flagged() -> None:
    commits = [
        Commit(
            sha="e" * 40,
            authored_at="2024-02-01T00:00:00Z",
            subject="Revert docs change",
            body="",
            files=("README.md", "docs/index.rst"),
        )
    ]
    assert detect_reverts(commits)[0].touches_python is False


def test_history_reading_counts_reverts_over_a_real_repo(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "r", {"pkg/config.py": "MAX = 1\n"})
    commit_file(repo, "pkg/config.py", "MAX = 2\n", "bump MAX (#2)")
    commit_file(repo, "pkg/config.py", "MAX = 1\n", 'Revert "bump MAX"\n\nThis reverts commit 1111111111111111111111111111111111111111.')
    branch = default_branch(repo)
    commits = read_history(repo, branch)
    assert len(commits) == 3
    reverts = detect_reverts(commits)
    assert len(reverts) == 1
    assert reverts[0].touches_python is True
    assert any(name == "pkg/config.py" for name in commits[0].files)


def test_parse_history_skips_noise_and_keeps_multiline_bodies() -> None:
    raw = "\x02sha\x1f2024-01-01T00:00:00Z\x1fSubject\x1fline one\nline two\x03\n\npkg/a.py\nREADME.md\n\n"
    commits = parse_history(raw)
    assert len(commits) == 1
    assert commits[0].body == "line one\nline two"
    assert commits[0].files == ("pkg/a.py", "README.md")


# Constant extraction


def test_constants_extracted_from_module_level_assignments() -> None:
    source = "MAX_RETRIES = 3\nTIMEOUT_MS = 500\n"
    found = {c.name: c.value for c in extract_constants(source, "pkg/config.py")}
    assert found == {"MAX_RETRIES": "3", "TIMEOUT_MS": "500"}


def test_annotated_assignment_is_extracted() -> None:
    found = {c.name: c.value for c in extract_constants("LIMIT: int = 10\n", "pkg/config.py")}
    assert found == {"LIMIT": "10"}


def test_non_literal_values_are_skipped() -> None:
    source = "COMPUTED = len('x')\nCALLED = make()\nGOOD = 7\n"
    found = {c.name for c in extract_constants(source, "pkg/config.py")}
    assert found == {"GOOD"}


def test_lowercase_names_are_skipped() -> None:
    source = "lower = 1\nMixedCase = 2\nUPPER = 3\n"
    found = {c.name for c in extract_constants(source, "pkg/config.py")}
    assert found == {"UPPER"}


def test_nested_assignments_are_skipped() -> None:
    source = "TOP = 1\n\ndef f():\n    NESTED = 2\n    return NESTED\n"
    found = {c.name for c in extract_constants(source, "pkg/config.py")}
    assert found == {"TOP"}


def test_non_string_literal_values_are_kept_as_repr() -> None:
    source = "NAMES = ['a', 'b']\nFLAG = True\n"
    found = {c.name: c.value for c in extract_constants(source, "pkg/config.py")}
    assert found["NAMES"] == "['a', 'b']"
    assert found["FLAG"] == "True"


def test_target_code_is_parsed_and_never_executed() -> None:
    source = (
        "raise SystemExit('this module must never be imported')\n"
        "MAX_RETRIES = 3\n"
        "import nonexistent_module_xyz\n"
    )
    found = {c.name for c in extract_constants(source, "pkg/config.py")}
    assert found == {"MAX_RETRIES"}


def test_syntax_error_raises_rather_than_being_swallowed(tmp_path: Path) -> None:
    with pytest.raises(SyntaxError):
        extract_constants("def broken(:\n", "pkg/config.py")


def test_package_directory_prefers_src_layout(tmp_path: Path) -> None:
    (tmp_path / "src" / "netclient").mkdir(parents=True)
    assert find_package_directory(tmp_path, "netclient") == tmp_path / "src" / "netclient"


def test_package_directory_falls_back_to_top_level(tmp_path: Path) -> None:
    (tmp_path / "celery").mkdir()
    assert find_package_directory(tmp_path, "celery") == tmp_path / "celery"


def test_package_directory_missing_returns_none(tmp_path: Path) -> None:
    assert find_package_directory(tmp_path, "absent") is None


def test_test_and_docs_directories_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "pkg" / "tests").mkdir(parents=True)
    (tmp_path / "pkg" / "docs").mkdir(parents=True)
    (tmp_path / "pkg" / "config.py").write_text("REAL = 1\n")
    (tmp_path / "pkg" / "tests" / "test_a.py").write_text("FAKE = 1\n")
    (tmp_path / "pkg" / "docs" / "conf.py").write_text("FAKE2 = 1\n")
    found = {c.name for c in collect_constants(tmp_path / "pkg", tmp_path)}
    assert found == {"REAL"}


# Constant history


def test_git_log_g_counts_every_commit_touching_the_line(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "r", {"pkg/config.py": "MAX_RETRIES = 3\nOTHER = 1\n"})
    commit_file(repo, "pkg/config.py", "MAX_RETRIES = 6\nOTHER = 1\n", "raise to six (#41)")
    commit_file(repo, "pkg/config.py", "MAX_RETRIES = 3\nOTHER = 1\n", "revert to three (#90)")
    constant = next(c for c in collect_constants(repo / "pkg", repo) if c.name == "MAX_RETRIES")
    history = constant_history(repo, constant)
    assert history.commits == 3
    assert history.value == "3"
    assert history.first_commit_at is not None
    assert history.last_commit_at is not None


def test_git_log_g_ignores_commits_that_do_not_touch_the_constant(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "r", {"pkg/config.py": "MAX_RETRIES = 3\nOTHER = 1\n"})
    commit_file(repo, "pkg/config.py", "MAX_RETRIES = 3\nOTHER = 2\n", "change something else")
    constant = next(c for c in collect_constants(repo / "pkg", repo) if c.name == "MAX_RETRIES")
    assert constant_history(repo, constant).commits == 1


def test_constant_history_counts_pull_request_references(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "r", {"pkg/config.py": "MAX_RETRIES = 3\n"})
    commit_file(repo, "pkg/config.py", "MAX_RETRIES = 6\n", "raise to six (#41)")
    commit_file(repo, "pkg/config.py", "MAX_RETRIES = 9\n", "raise again with no pr ref")
    constant = next(c for c in collect_constants(repo / "pkg", repo) if c.name == "MAX_RETRIES")
    history = constant_history(repo, constant)
    assert history.commits == 3
    assert history.with_pull_request == 1


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("Raise the cap (#41)", True),
        ("Merge pull request #77 from acme/feature", True),
        ("Raise the cap", False),
        ("Fix (#not-a-number)", True),
        ("", False),
    ],
)
def test_pull_request_reference_detection(subject: str, expected: bool) -> None:
    assert has_pull_request_reference(subject) is expected


def test_constant_value_is_truncated_for_display(tmp_path: Path) -> None:
    repo = build_repo(tmp_path / "r", {"pkg/config.py": "LONG = '" + ("x" * 200) + "'\n"})
    constant = next(c for c in collect_constants(repo / "pkg", repo) if c.name == "LONG")
    assert len(constant.truncated_value) == 40
    history = constant_history(repo, constant)
    assert len(history.truncated_value) == 40


# Clone safety


@pytest.mark.parametrize("repo", ["urllib3/urllib3", "psf/requests"])
def test_clone_url_is_github_only(repo: str) -> None:
    assert clone_url(repo) == f"https://github.com/{repo}"


@pytest.mark.parametrize("repo", ["not-a-repo", "a/b/c", "/requests", "", "  "])
def test_non_owner_name_repositories_are_refused(repo: str) -> None:
    with pytest.raises(InvalidRepositoryError):
        clone_url(repo)


@pytest.mark.parametrize("repo", ["gitlab.com/x/y", "bitbucket.org/x/y", "https://github.com/a/b"])
def test_parse_slug_refuses_non_owner_name_input(repo: str) -> None:
    with pytest.raises(InvalidRepositoryError):
        parse_slug(repo)


def test_clone_is_refused_before_running_git_when_the_size_hint_exceeds_the_limit(
    tmp_path: Path,
) -> None:
    def never_called(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
        raise AssertionError("git must not run when the size hint already exceeds the limit")

    with pytest.raises(RepositoryTooLargeError) as excinfo:
        clone_repository(
            "acme/big",
            tmp_path / "clones",
            runner=never_called,
            size_limit_mb=100,
            size_hint_mb=5000.0,
        )
    assert "not cloning" in str(excinfo.value)


def test_clone_is_refused_when_the_cloned_tree_exceeds_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.ingest.git_probe as probe

    def fake_runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
        Path(command[-1]).mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(probe, "directory_size_bytes", lambda path: 50 * 1024 * 1024)
    with pytest.raises(RepositoryTooLargeError) as excinfo:
        clone_repository("acme/big", tmp_path / "clones", runner=fake_runner, size_limit_mb=10)
    assert "cloned to 50 MB" in str(excinfo.value)


def test_clone_command_never_uses_a_shell_and_disables_prompts_and_hooks(
    tmp_path: Path,
) -> None:
    captured: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
        captured.append(list(command))
        Path(command[-1]).mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(command, 0, "", "")

    clone_repository("acme/netclient", tmp_path / "clones", runner=fake_runner)
    command = captured[0]
    assert command[0] == "git"
    assert isinstance(command, list)
    assert command[-1].endswith("acme__netclient")
    assert "submodule.recurse=false" in command
    assert "core.hooksPath=" in command
    assert "--no-recurse-submodules" in command
    assert "--depth" not in command
    assert "--filter" not in command
    assert "--single-branch" not in command
    assert "https://github.com/acme/netclient" in command
    assert command.index("--no-recurse-submodules") < command.index(
        "https://github.com/acme/netclient"
    )


def test_git_environment_disables_credential_prompts() -> None:
    from app.services.ingest.git_probe import git_environment

    environment = git_environment()
    assert environment["GIT_TERMINAL_PROMPT"] == "0"


def test_a_failing_clone_raises_without_leaking_a_stack_trace(tmp_path: Path) -> None:
    def failing(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, 128, "", "fatal: repository not found")

    with pytest.raises(GitProbeError) as excinfo:
        clone_repository("acme/absent", tmp_path / "clones", runner=failing)
    assert "repository not found" in str(excinfo.value)


def test_clone_returns_an_existing_directory_without_running_git(tmp_path: Path) -> None:
    destination = tmp_path / "clones" / "acme__already"
    destination.mkdir(parents=True)

    def never_called(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
        raise AssertionError("an existing clone must not be re-cloned")

    assert clone_repository("acme/already", tmp_path / "clones", runner=never_called) == destination
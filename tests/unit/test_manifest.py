"""Scenario provenance behavior in minimal deployment images."""

import subprocess
from pathlib import Path

from traffic_platform.scenario_engine.manifest import git_revision


def test_git_revision_degrades_when_git_is_not_installed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def missing_git(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", missing_git)
    assert git_revision(tmp_path) == "UNAVAILABLE_GIT_NOT_INSTALLED"

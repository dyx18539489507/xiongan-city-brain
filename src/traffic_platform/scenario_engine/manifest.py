"""Hash-based scenario provenance manifests."""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    """Return a lowercase SHA-256 digest without changing the source."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision(workspace: Path) -> str:
    """Return the current revision or an explicit uncommitted marker."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        return "UNAVAILABLE_GIT_NOT_INSTALLED"
    except subprocess.TimeoutExpired:
        return "UNAVAILABLE_GIT_TIMEOUT"
    except OSError as exc:
        return f"UNAVAILABLE_GIT_OSERROR_{exc.errno or 'UNKNOWN'}"
    return result.stdout.strip() if result.returncode == 0 else "UNCOMMITTED"


def build_manifest(
    scenario_id: str,
    files: list[Path],
    *,
    workspace: Path,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Create a deterministic manifest for the exact generated scenario files."""

    file_entries = [
        {
            "path": path.relative_to(workspace).as_posix(),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(files)
    ]
    canonical = json.dumps(file_entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "scenario_hash": hashlib.sha256(canonical).hexdigest(),
        "files": file_entries,
        "provenance": provenance,
        "git_revision": git_revision(workspace),
    }

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path, PurePosixPath


MANIFEST_ENTRY = re.compile(r"^[0-9a-fA-F]{64}  (.+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a portable ZIP from SHA256SUMS.txt")
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    return parser.parse_args()


def load_files(package: Path, manifest: Path) -> list[tuple[Path, str]]:
    relative_paths: list[str] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = MANIFEST_ENTRY.fullmatch(line)
        if not match:
            raise ValueError(f"Invalid SHA256SUMS entry: {line}")
        relative_paths.append(match.group(1))
    if "SHA256SUMS.txt" not in relative_paths:
        relative_paths.append("SHA256SUMS.txt")

    files: list[tuple[Path, str]] = []
    for relative in relative_paths:
        posix_path = PurePosixPath(relative)
        if posix_path.is_absolute() or ".." in posix_path.parts:
            raise ValueError(f"Unsafe manifest path: {relative}")
        source = package.joinpath(*posix_path.parts).resolve(strict=True)
        source.relative_to(package)
        if not source.is_file():
            raise FileNotFoundError(f"Manifest file is missing: {relative}")
        files.append((source, relative))
    return files


def main() -> None:
    args = parse_args()
    package = args.package.resolve(strict=True)
    archive = args.archive.resolve(strict=False)
    manifest = (args.manifest or package / "SHA256SUMS.txt").resolve(strict=True)
    files = load_files(package, manifest)

    with zipfile.ZipFile(
        archive,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
        strict_timestamps=False,
    ) as output:
        for source, relative in files:
            output.write(source, f"{package.name}/{relative}")

    print(f"Portable ZIP created: {archive}")
    print(f"Files: {len(files)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Select example images affected by uncommitted example/Fabric inputs.

Adapted from light-fabric/scripts/select-changed-apps.py. Cargo's resolved
dependency graph includes the examples' sibling Fabric path dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


TARGET_PACKAGES = {
    "demo-support-triage-agent": ("demo-support-triage-agent",),
    "demo-customer-profile-api": ("demo-customer-profile-api",),
    "demo-insurance-claim-mcp-server": ("demo-insurance-claim-mcp-server",),
    "demo-offer-decision-api": ("demo-offer-decision-api",),
}

# Root directories that belong to no Cargo package but are compiled into
# binaries through include_str!/include_bytes! or build scripts.
SHARED_SOURCE_DIRS = {"contracts"}


class SelectionError(Exception):
    pass


def run_bytes(args: list[str], cwd: Path) -> bytes:
    return subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.PIPE).stdout


def changed_paths(root: Path) -> set[Path]:
    tracked = run_bytes(["git", "diff", "--no-renames", "--name-only", "-z", "HEAD"], root)
    untracked = run_bytes(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], root
    )
    names = set(tracked.split(b"\0")) | set(untracked.split(b"\0"))
    return {root / os.fsdecode(name) for name in names if name}


def cargo_metadata(root: Path) -> dict:
    output = run_bytes(
        ["cargo", "metadata", "--locked", "--format-version", "1",
         "--filter-platform", "x86_64-unknown-linux-musl"], root
    )
    return json.loads(output)


def global_input(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    parts = relative.parts
    if relative.name in {"Cargo.toml", "Cargo.lock", ".dockerignore"} and len(parts) == 1:
        return True
    if relative.name in {"rust-toolchain", "rust-toolchain.toml"} and len(parts) == 1:
        return True
    if relative.as_posix() in {"docker/Dockerfile", "docker/Dockerfile.dockerignore"}:
        return True
    return bool(parts and parts[0] in {".cargo", "patches"})


def rust_sources(directory: Path) -> list[Path]:
    return [
        source
        for source in directory.rglob("*.rs")
        if "target" not in source.relative_to(directory).parts
    ]


def shared_source_readers(
    path: Path, root: Path, package_dirs: list[tuple[Path, dict]]
) -> set[str] | None:
    """Return packages whose Rust sources name the changed shared directory.

    None means the path is not under a shared source directory. An empty set
    means no reader was found, which callers must treat conservatively.
    """
    parts = path.relative_to(root).parts
    if len(parts) < 3 or parts[0] not in SHARED_SOURCE_DIRS:
        return None
    needle = f"{parts[0]}/{parts[1]}/"
    readers: set[str] = set()
    for directory, package in package_dirs:
        if package.get("source") is not None:
            continue
        for source in rust_sources(directory):
            if needle in source.read_text(encoding="utf-8", errors="replace"):
                readers.add(package["id"])
                break
    return readers


def select_images(
    root: Path, dirty: set[Path], metadata: dict, requested: set[str]
) -> list[str]:
    unknown = requested - set(TARGET_PACKAGES)
    if unknown:
        raise SelectionError(f"Unknown image selection: {', '.join(sorted(unknown))}")

    packages = metadata["packages"]
    by_id = {package["id"]: package for package in packages}
    resolve = metadata.get("resolve") or {}
    if not resolve.get("nodes"):
        raise SelectionError("Cargo metadata is missing the resolved dependency graph")
    deps: dict[str, set[str]] = {
        node["id"]: {edge["pkg"] for edge in node.get("deps", [])}
        for node in resolve.get("nodes", [])
    }
    package_dirs = sorted(
        ((Path(package["manifest_path"]).parent.resolve(), package) for package in packages),
        key=lambda item: len(item[0].parts),
        reverse=True,
    )

    changed_package_ids: set[str] = set()
    global_change = False
    for path in sorted(dirty):
        input_root = next(
            (candidate for candidate in (root, root.parent / "light-fabric")
             if path.is_relative_to(candidate)), None
        )
        if input_root is None:
            continue
        relative = path.relative_to(input_root)
        if global_input(path, input_root):
            global_change = True
            print(f"Changed build-wide input: {relative}", file=sys.stderr)
            continue
        owner = next(
            (package for directory, package in package_dirs if path.is_relative_to(directory)),
            None,
        )
        if owner is not None:
            changed_package_ids.add(owner["id"])
            print(f"Changed package input: {relative} -> {owner['name']}", file=sys.stderr)
            continue
        readers = shared_source_readers(path, input_root, package_dirs)
        if readers is None:
            print(f"Changed non-image input: {relative}", file=sys.stderr)
        elif readers:
            changed_package_ids |= readers
            names = ", ".join(sorted(by_id[reader]["name"] for reader in readers))
            print(f"Changed shared source: {relative} -> {names}", file=sys.stderr)
        else:
            global_change = True
            print(f"Changed shared source with no known reader: {relative}", file=sys.stderr)

    target_ids: dict[str, set[str]] = {}
    for image, names in TARGET_PACKAGES.items():
        target_ids[image] = {
            package["id"] for package in packages if package["name"] in names
        }
        missing = set(names) - {by_id[package_id]["name"] for package_id in target_ids[image]}
        if missing:
            raise SelectionError(
                f"Cargo package(s) missing for {image}: {', '.join(sorted(missing))}"
            )
        if not target_ids[image].issubset(deps):
            raise SelectionError(f"Resolved dependency graph is incomplete for {image}")

    affected: list[str] = []
    for image, ids in target_ids.items():
        if requested and image not in requested:
            continue
        closure = set(ids)
        pending = list(ids)
        while pending:
            current = pending.pop()
            for dependency in deps.get(current, set()):
                if dependency not in closure:
                    closure.add(dependency)
                    pending.append(dependency)
        if global_change or closure.intersection(changed_package_ids):
            affected.append(image)
            reason = "workspace-wide build input" if global_change else "Cargo dependency"
            print(f"Selected image: {image} ({reason})", file=sys.stderr)
    return affected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--only", action="append", default=[])
    args = parser.parse_args()

    root = args.root.resolve()
    try:
        dirty = changed_paths(root) | changed_paths(root.parent / "light-fabric")
        if not dirty:
            print("No uncommitted files; no images selected.", file=sys.stderr)
            return 0
        metadata = cargo_metadata(root)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"Unable to inspect Cargo workspace: {exc}", file=sys.stderr)
        return 2

    try:
        affected = select_images(root, dirty, metadata, set(args.only))
    except SelectionError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not affected:
        print("No selected images are affected by uncommitted files.", file=sys.stderr)
        return 0
    print("\n".join(affected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

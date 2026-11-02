"""
V2.6 source integrity — the manifest of the *current* application source tree.

Why this exists
---------------
The V2.3, V2.4 and V2.5 evaluation runs each recorded, inside their own
metadata file, a manifest of the V1 application source they were run against
(group ``v1_backend_and_frontend_source`` = every file under ``backend/app/**``
and ``src/**`` at that time). Those recorded manifests are historical evidence
of the code used for those experiments. They are immutable and are never
regenerated.

V2.6 (investigator workflow + audit trail) is an *intentional* evolution of the
application code after those frozen runs. It adds and modifies files under
``backend/app/**`` and ``src/**`` and does not touch the V1 intelligence engine,
the risk formulas, or any V2.1-V2.5 evaluation data, labels, predictions or results.

So two different questions are verified separately:

  1. HISTORICAL FREEZE  - are the V2.3-V2.5 experiments' recorded manifests and
     artifacts intact, and is everything that was frozen *except* the declared
     V2.6 application changes still byte-identical?   (evaluation/tests, via
     ``frozen_diff`` below)
  2. CURRENT V2.6 SOURCE - does the application source tree on disk match the
     V2.6 manifest committed with it?   (backend/tests/test_v2_6_source_integrity.py)

The V2.6 manifest (backend/v2_6_source_manifest.json) is deliberately stored
OUTSIDE ``backend/app`` and ``src`` so it never hashes itself.

It covers the source that git can ship. The historical runs walked the filesystem and so
also recorded one git-ignored, local-only file (src/imports/pasted_text/pasted-attachment.txt)
that no clean checkout contains; EXCLUDED_LOCAL_ONLY_PATHS names it explicitly. The
historical manifests still record it, unchanged.

Hashing rules (deterministic, machine-independent)
-------------------------------------------------
  * SHA-256, hex digest
  * repo-relative POSIX paths, sorted; no absolute paths, no timestamps
  * UTF-8 JSON, ``sort_keys``, 2-space indent, LF newlines, trailing newline
  * text files are hashed with CRLF normalised to LF, so a Windows checkout
    with ``core.autocrlf`` does not change a hash

Commands (run from the repository root)
---------------------------------------
    python -m backend.v2_6_integrity --check    # verify; exit 1 on any mismatch
    python -m backend.v2_6_integrity --write    # regenerate the V2.6 manifest
                                                # (only when the source change is intended)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

SCOPE = ("backend/app", "src")
HISTORICAL_GROUP = "v1_backend_and_frontend_source"
# Local-only paths that the V2.6 manifest deliberately does NOT cover. Each must be (a) listed in
# .gitignore, so a clean checkout cannot contain it, and (b) referenced by no source file. The
# historical V2.3-V2.5 runs walked the filesystem and so recorded one such file; it is still in
# those (immutable) manifests, but a clean clone can never have it. Keep this list minimal: a path
# belongs here only if the two conditions above hold (enforced by test_v2_6_source_integrity.py).
EXCLUDED_LOCAL_ONLY_PATHS = ("src/imports/pasted_text/",)
MANIFEST_RELPATH = "backend/v2_6_source_manifest.json"
# The historical manifests, recorded by the V2.3 / V2.4 / V2.5 runs. Read-only here.
HISTORICAL_MANIFEST_FILES = (
    "evaluation/baseline_predictions_meta.json",
    "evaluation/ablation/ablation_predictions_meta.json",
    "evaluation/calibration/calibration_metadata.json",
)
TEXT_EXTENSIONS = frozenset({".py", ".ts", ".tsx", ".css", ".html", ".txt", ".json", ".md", ".mjs"})
SCHEMA_VERSION = 1


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def is_excluded(rel: str) -> bool:
    """True for a repo-relative POSIX path in EXCLUDED_LOCAL_ONLY_PATHS."""
    return rel.startswith(EXCLUDED_LOCAL_ONLY_PATHS)


# ----------------------------------------------------------------- hashing --


def raw_sha256(path: Path) -> str:
    """Byte-for-byte SHA-256 — the method the historical manifests used."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalized_sha256(path: Path) -> str:
    """SHA-256 with CRLF -> LF for text files (V2.6 manifest method)."""
    data = Path(path).read_bytes()
    if Path(path).suffix.lower() in TEXT_EXTENSIONS:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def sha256_line_ending_variants(path: Path) -> set[str]:
    """
    The SHA-256 values one file's *content* can have under line-ending rewriting: as stored (raw),
    with CRLF->LF, and with every LF as CRLF. Non-text files have only the raw hash.

    The historical manifests recorded RAW hashes of a Windows working tree, where a file may have
    CRLF line endings while the git blob (and so a Linux/CI checkout) has LF, e.g. with
    ``core.autocrlf``. Line endings are not content, so comparing to a recorded hash must tolerate
    them. Any change to the actual content changes all three values, so this stays strict.
    """
    data = Path(path).read_bytes()
    out = {hashlib.sha256(data).hexdigest()}
    if Path(path).suffix.lower() in TEXT_EXTENSIONS:
        lf = data.replace(b"\r\n", b"\n")
        out.add(hashlib.sha256(lf).hexdigest())
        out.add(hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest())
    return out


def matches_recorded(path: Path, recorded_sha256: str) -> bool:
    """True if the file's content equals the recorded hash, ignoring line-ending differences only."""
    return recorded_sha256 in sha256_line_ending_variants(path)


def walk_scope(root: Path) -> list[str]:
    """Sorted repo-relative POSIX paths of every file in scope (no bytecode caches)."""
    found: list[str] = []
    for base in SCOPE:
        for dirpath, dirnames, filenames in os.walk(root / base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if name.endswith((".pyc", ".pyo")):
                    continue
                rel = Path(dirpath, name).relative_to(root).as_posix()
                if not is_excluded(rel):
                    found.append(rel)
    return sorted(found)


# ------------------------------------------------------ historical snapshot --


def historical_snapshot(root: Path) -> dict[str, str]:
    """The V1 backend/frontend snapshot recorded by the V2.3 run (raw SHA-256 per file)."""
    meta = json.loads((root / HISTORICAL_MANIFEST_FILES[0]).read_text(encoding="utf-8"))
    return {k: v for k, v in meta["frozen_manifest"][HISTORICAL_GROUP].items() if not is_excluded(k)}


def historical_snapshots_agree(root: Path) -> bool:
    """V2.3, V2.4 and V2.5 each recorded the V1 snapshot; they must all describe the same one."""
    snaps = [
        json.loads((root / rel).read_text(encoding="utf-8"))["frozen_manifest"][HISTORICAL_GROUP]
        for rel in HISTORICAL_MANIFEST_FILES
    ]
    return all(s == snaps[0] for s in snaps)


def diff_from_historical(root: Path) -> dict[str, list[str]]:
    """Exactly which files differ in CONTENT between the recorded V1 snapshot and the tree on disk (line endings ignored)."""
    old = historical_snapshot(root)
    now = set(walk_scope(root))
    return {
        "modified": sorted(k for k in old if k in now and not matches_recorded(root / k, old[k])),
        "added": sorted(k for k in now if k not in old),
        "removed": sorted(k for k in old if k not in now),
    }


# ---------------------------------------------------------------- manifest --


def build_manifest(root: Path | None = None) -> dict:
    root = Path(root) if root else repo_root()
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Integrity manifest of the V2.6 application source tree. V2.6 is an intentional evolution of "
            "backend/app/** and src/** after the frozen V2.3-V2.5 evaluation runs; the historical manifests "
            "recorded by those runs are unchanged and are pinned below."
        ),
        "hashing": {
            "algorithm": "sha256",
            "paths": "repo-relative POSIX, sorted",
            "text_newlines": "CRLF normalised to LF before hashing",
            "encoding": "UTF-8",
        },
        "scope": [f"{b}/**" for b in SCOPE],
        "excluded_local_only_paths": list(EXCLUDED_LOCAL_ONLY_PATHS),
        "historical_manifest_sha256": {rel: normalized_sha256(root / rel) for rel in HISTORICAL_MANIFEST_FILES},
        "v2_6_changes_from_v1_snapshot": diff_from_historical(root),
        "files": {rel: normalized_sha256(root / rel) for rel in walk_scope(root)},
    }


def render(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def load_manifest(root: Path | None = None) -> dict:
    root = Path(root) if root else repo_root()
    return json.loads((root / MANIFEST_RELPATH).read_text(encoding="utf-8"))


def verify(root: Path | None = None, manifest: dict | None = None) -> list[str]:
    """Problems found comparing the tree on disk with the V2.6 manifest (empty list = intact)."""
    root = Path(root) if root else repo_root()
    manifest = manifest if manifest is not None else load_manifest(root)
    problems: list[str] = []
    if manifest.get("excluded_local_only_paths") != list(EXCLUDED_LOCAL_ONLY_PATHS):
        problems.append("excluded_local_only_paths in the manifest differs from the tool's exclusion list")
    on_disk = walk_scope(root)
    recorded = manifest["files"]
    for rel in sorted(set(recorded) - set(on_disk)):
        problems.append(f"missing: {rel}")
    for rel in sorted(set(on_disk) - set(recorded)):
        problems.append(f"unexpected (not in V2.6 manifest): {rel}")
    for rel in sorted(set(on_disk) & set(recorded)):
        if normalized_sha256(root / rel) != recorded[rel]:
            problems.append(f"modified: {rel}")
    for rel, sha in manifest["historical_manifest_sha256"].items():
        if not (root / rel).is_file():
            problems.append(f"historical manifest missing: {rel}")
        elif normalized_sha256(root / rel) != sha:
            problems.append(f"historical manifest changed: {rel}")
    return problems


# --------------------------------------------- hook for the historical tests --


def frozen_diff(recorded: dict, now: dict, manifest: dict | None = None, root: Path | None = None) -> dict[str, list[str]]:
    """
    Drop-in replacement for the comparison the V2.3/V2.4/V2.5 freeze tests make:
    ``{group: [paths whose current hash differs from the recorded one]}``, empty groups omitted.

    Every group is compared exactly as before — except the V1 backend/frontend group, where
    the files V2.6 declares it added/modified/removed (backend/v2_6_source_manifest.json) are
    tolerated, as is the one git-ignored local-only path in EXCLUDED_LOCAL_ONLY_PATHS (absent
    from any clean clone), as is a file whose content is unchanged and only its line endings
    differ (see ``sha256_line_ending_variants``). Any *other* difference in that group, and any difference in any other group
    (V1 intelligence, V2.1 dataset/spec, V2.2, V2.3, V2.4), is still reported.
    """
    root = Path(root) if root else repo_root()
    manifest = manifest if manifest is not None else load_manifest(root)
    declared = manifest["v2_6_changes_from_v1_snapshot"]
    allowed = set(declared["modified"]) | set(declared["added"]) | set(declared["removed"])
    out: dict[str, list[str]] = {}
    for group in recorded:
        differing = sorted(k for k in set(now[group]) | set(recorded[group]) if now[group].get(k) != recorded[group].get(k))
        if group == HISTORICAL_GROUP:
            # In this group only, a file whose content is unchanged but whose line endings were rewritten
            # by the checkout is not a difference. Every other group stays byte-exact.
            differing = [
                k for k in differing
                if k not in allowed and not is_excluded(k)
                and not (k in recorded[group] and (root / k).is_file() and matches_recorded(root / k, recorded[group][k]))
            ]
        if differing:
            out[group] = differing
    return out


# --------------------------------------------------------------------- CLI --


def main(argv: list[str]) -> int:
    root = repo_root()
    if "--write" in argv:
        (root / MANIFEST_RELPATH).write_bytes(render(build_manifest(root)).encode("utf-8"))
        print(f"wrote {MANIFEST_RELPATH}")
        return 0
    problems = verify(root)
    for p in problems:
        print(p)
    print("V2.6 source integrity: OK" if not problems else f"V2.6 source integrity: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

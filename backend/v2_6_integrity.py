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

Layers (post-V2.6 changes)
--------------------------
  Layer 0  the V2.3-V2.5 manifests / V1 snapshot            immutable, pinned by the V2.6 manifest
  Layer 1  backend/v2_6_source_manifest.json                  immutable, pinned by the ledger (SHA-256)
  Layer 2  backend/post_v2_6_changes.json                     append-only, hash-chained change ledger
  Layer 3  the current tree, verified against Layer 1 + Layer 2 (the "effective" manifest)

Source changes made AFTER V2.6 are never written into the V2.6 manifest. Each is declared as a
ledger entry (path, modified|added, base_sha256, sha256); the base must equal the effective hash
immediately before the change and the file on disk must equal the declared new hash. Anything
else - an undeclared edit, a wrong hash, an extra or missing file - fails ``verify``. The ledger
may not declare changes under intelligence/**, evaluation/**, backend/app/auth/**, backend/app/db/**,
or to any V1 file under backend/app/intelligence/**. See backend/V2_6_SOURCE_INTEGRITY.md.

Commands (run from the repository root)
---------------------------------------
    python -m backend.v2_6_integrity --check    # verify (layered); exit 1 on any mismatch
    python -m backend.v2_6_integrity --write    # regenerate the V2.6 manifest - REFUSED once
                                                # backend/post_v2_6_changes.json exists; record
                                                # later changes in the ledger instead
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
LEDGER_RELPATH = "backend/post_v2_6_changes.json"
LEDGER_SCHEMA_VERSION = 1
# The ledger may never declare changes to these (each is protected by an existing mechanism).
LEDGER_FORBIDDEN_PREFIXES = ("intelligence/", "evaluation/", "backend/app/auth/", "backend/app/db/")
# Files recorded in the V1 snapshot under these prefixes may not be modified via the ledger
# (new files may be added, e.g. backend/app/intelligence/cache.py).
LEDGER_V1_PROTECTED_PREFIXES = ("backend/app/intelligence/",)
_HEX64 = frozenset("0123456789abcdef")


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


# ----------------------------------------------------- post-V2.6 change ledger --


def ledger_exists(root: Path | None = None) -> bool:
    return ((Path(root) if root else repo_root()) / LEDGER_RELPATH).is_file()


def load_ledger(root: Path | None = None) -> dict:
    root = Path(root) if root else repo_root()
    return json.loads((root / LEDGER_RELPATH).read_text(encoding="utf-8"))


def entry_digest(entry: dict) -> str:
    """Deterministic SHA-256 of a ledger entry's content (its own digest field excluded)."""
    body = {k: entry.get(k) for k in ("id", "description", "previous_entry_sha256", "files")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX64


def _path_problem(rel: str, v1_snapshot: dict[str, str]) -> str | None:
    if not rel or rel.startswith("/") or "\\" in rel or ":" in rel or ".." in rel.split("/"):
        return "path is not a clean repo-relative POSIX path"
    if rel.startswith(LEDGER_FORBIDDEN_PREFIXES):
        return "path is protected and may not be declared in the ledger"
    if not rel.startswith(tuple(f"{b}/" for b in SCOPE)):
        return "path is outside the verified scope"
    if is_excluded(rel):
        return "path is a local-only excluded path"
    if rel.startswith(LEDGER_V1_PROTECTED_PREFIXES) and rel in v1_snapshot:
        return "path is a V1 protected file and may not be modified"
    return None


def apply_ledger(root: Path | None = None, manifest: dict | None = None) -> tuple[dict[str, str], list[str], list[tuple[str, str]]]:
    """
    Layer 1 + Layer 2: ``(effective_files, problems, declared_changes)``.

    ``effective_files`` is the V2.6 manifest's ``files`` overlaid with every valid ledger entry, in
    order. ``problems`` lists everything wrong with the ledger itself (pin, chain, base hashes,
    forbidden paths, malformed data); an entry or file with a problem is not applied.
    ``declared_changes`` is ``[(path, "modified"|"added"), ...]`` for the applied changes.
    """
    root = Path(root) if root else repo_root()
    manifest = manifest if manifest is not None else load_manifest(root)
    expected: dict[str, str] = dict(manifest["files"])
    problems: list[str] = []
    changes: list[tuple[str, str]] = []
    try:
        ledger = load_ledger(root)
    except (OSError, ValueError) as exc:
        return expected, [f"ledger unreadable: {LEDGER_RELPATH} ({exc.__class__.__name__})"], changes

    v1 = historical_snapshot(root)
    pinned = (ledger.get("v2_6_manifest") or {})
    live = normalized_sha256(root / MANIFEST_RELPATH) if (root / MANIFEST_RELPATH).is_file() else None
    if pinned.get("path") != MANIFEST_RELPATH or not _is_hex64(pinned.get("sha256")):
        problems.append("ledger: v2_6_manifest pin is malformed")
    elif live != pinned["sha256"]:
        problems.append(f"historical V2.6 manifest changed: {MANIFEST_RELPATH}")
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        problems.append("ledger: unsupported schema_version")
    entries = ledger.get("changes")
    if not isinstance(entries, list) or not entries:
        return expected, problems + ["ledger: 'changes' must be a non-empty list"], changes

    previous = pinned.get("sha256")  # the first entry chains to the pinned V2.6 manifest
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"ledger entry #{index + 1} ({entry.get('id')!r})" if isinstance(entry, dict) else f"ledger entry #{index + 1}"
        if not isinstance(entry, dict) or not isinstance(entry.get("files"), list) or not entry["files"]:
            problems.append(f"{label}: malformed")
            continue
        if entry.get("id") in seen_ids or not entry.get("id"):
            problems.append(f"{label}: missing or duplicate id")
        seen_ids.add(entry.get("id"))
        if entry.get("previous_entry_sha256") != previous:
            problems.append(f"{label}: previous_entry_sha256 does not chain to the preceding ledger state")
        digest = entry_digest(entry)
        if entry.get("entry_sha256") != digest:
            problems.append(f"{label}: entry_sha256 does not match its content")
        previous = entry.get("entry_sha256")  # chain on what is recorded, so one edit breaks every later link

        paths = [f.get("path") for f in entry["files"] if isinstance(f, dict)]
        if paths != sorted(paths) or len(set(paths)) != len(paths):
            problems.append(f"{label}: files must be sorted by path with no duplicates")
        for f in entry["files"]:
            if not isinstance(f, dict) or not isinstance(f.get("path"), str):
                problems.append(f"{label}: malformed file record")
                continue
            rel, kind, base, new = f["path"], f.get("change"), f.get("base_sha256"), f.get("sha256")
            reason = _path_problem(rel, v1)
            if reason:
                problems.append(f"{label}: {rel}: {reason}")
                continue
            if kind not in ("modified", "added") or not _is_hex64(new) or not (base is None or _is_hex64(base)):
                problems.append(f"{label}: {rel}: malformed change record")
                continue
            if kind == "added":
                if base is not None or rel in expected:
                    problems.append(f"{label}: {rel}: an added file must have base_sha256 null and must not already exist")
                    continue
            else:
                if base is None or expected.get(rel) != base:
                    problems.append(f"{label}: {rel}: base_sha256 does not equal the effective hash before this change")
                    continue
                if new == base:
                    problems.append(f"{label}: {rel}: modified entry does not change the hash")
                    continue
            expected[rel] = new
            changes.append((rel, kind))
    return expected, problems, changes


def declared_changes_from_v1(root: Path | None = None, manifest: dict | None = None) -> dict[str, list[str]]:
    """What differs from the recorded V1 snapshot *by declaration*: the V2.6 list plus the ledger's changes."""
    root = Path(root) if root else repo_root()
    manifest = manifest if manifest is not None else load_manifest(root)
    base = manifest["v2_6_changes_from_v1_snapshot"]
    modified, added, removed = set(base["modified"]), set(base["added"]), set(base["removed"])
    if ledger_exists(root):
        snapshot = historical_snapshot(root)
        for rel, kind in apply_ledger(root, manifest)[2]:
            if kind == "added":
                added.add(rel)
            elif rel in snapshot:
                modified.add(rel)  # (a file V2.6 itself added is already in `added`)
    return {"added": sorted(added), "modified": sorted(modified), "removed": sorted(removed)}


def effective_manifest(root: Path | None = None) -> dict:
    """The expected current manifest: V2.6 manifest + declared post-V2.6 changes (same shape as ``build_manifest``)."""
    root = Path(root) if root else repo_root()
    manifest = load_manifest(root)
    files, problems, _ = apply_ledger(root, manifest)
    if problems:
        raise ValueError("post-V2.6 ledger is invalid: " + "; ".join(problems))
    return {**manifest, "files": dict(sorted(files.items())), "v2_6_changes_from_v1_snapshot": declared_changes_from_v1(root, manifest)}


def ledger_tolerated_paths(root: Path | None = None) -> set[str]:
    """Paths the ledger legitimately accounts for: ledger valid AND the file on disk equals the declared hash."""
    root = Path(root) if root else repo_root()
    if not ledger_exists(root):
        return set()
    files, problems, changes = apply_ledger(root)
    if problems:
        return set()
    return {rel for rel, _ in changes if (root / rel).is_file() and normalized_sha256(root / rel) == files[rel]}


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
    """
    Problems found comparing the tree on disk with the expected source (empty list = intact).

    Expected source = the V2.6 manifest, plus the post-V2.6 ledger when backend/post_v2_6_changes.json
    exists. Without a ledger this is exactly the original V2.6 check.
    """
    root = Path(root) if root else repo_root()
    manifest = manifest if manifest is not None else load_manifest(root)
    problems: list[str] = []
    if manifest.get("excluded_local_only_paths") != list(EXCLUDED_LOCAL_ONLY_PATHS):
        problems.append("excluded_local_only_paths in the manifest differs from the tool's exclusion list")
    on_disk = walk_scope(root)
    recorded = manifest["files"]
    if ledger_exists(root):
        recorded, ledger_problems, _ = apply_ledger(root, manifest)
        problems.extend(ledger_problems)
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
    from any clean clone), as is a post-V2.6 change declared in the ledger with a matching hash, as is a file whose content is unchanged and only its line endings
    differ (see ``sha256_line_ending_variants``). Any *other* difference in that group, and any difference in any other group
    (V1 intelligence, V2.1 dataset/spec, V2.2, V2.3, V2.4), is still reported.
    """
    root = Path(root) if root else repo_root()
    manifest = manifest if manifest is not None else load_manifest(root)
    declared = manifest["v2_6_changes_from_v1_snapshot"]
    allowed = set(declared["modified"]) | set(declared["added"]) | set(declared["removed"])
    # Post-V2.6 changes are tolerated only when the ledger is valid AND the file on disk equals the
    # hash the ledger declares for it. (The V2.6 allowance above stays the historical, path-based one.)
    ledger_ok = ledger_tolerated_paths(root)
    out: dict[str, list[str]] = {}
    for group in recorded:
        differing = sorted(k for k in set(now[group]) | set(recorded[group]) if now[group].get(k) != recorded[group].get(k))
        if group == HISTORICAL_GROUP:
            # In this group only, a file whose content is unchanged but whose line endings were rewritten
            # by the checkout is not a difference. Every other group stays byte-exact.
            differing = [
                k for k in differing
                if k not in allowed and k not in ledger_ok and not is_excluded(k)
                and not (k in recorded[group] and (root / k).is_file() and matches_recorded(root / k, recorded[group][k]))
            ]
        if differing:
            out[group] = differing
    return out


# --------------------------------------------------------------------- CLI --


def main(argv: list[str]) -> int:
    root = repo_root()
    if "--write" in argv:
        if ledger_exists(root):
            print(
                f"REFUSED: {LEDGER_RELPATH} exists, so the historical V2.6 manifest ({MANIFEST_RELPATH}) is closed.\n"
                "Post-V2.6 source changes must be recorded as new entries in the ledger, not by regenerating the\n"
                "V2.6 manifest. Nothing was written.",
                file=sys.stderr,
            )
            return 2
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

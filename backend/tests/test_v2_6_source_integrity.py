"""
V2.6 source-integrity tests.

V2.6 is an intentional evolution of backend/app/** and src/** after the frozen
V2.3-V2.5 evaluation runs. This file verifies the CURRENT source tree against the
V2.6 manifest (backend/v2_6_source_manifest.json), and checks that the historical
manifests recorded by V2.3/V2.4/V2.5 are intact and are accounted for exactly.
See backend/v2_6_integrity.py for the rationale.

If one of these fails because application source was changed on purpose, review the
change and regenerate with:  python -m backend.v2_6_integrity --write
(Never regenerate to hide an unexpected difference. The historical V2.3-V2.5
manifests and artifacts are never regenerated.)
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from backend import v2_6_integrity as I

ROOT = I.repo_root()
MANIFEST = ROOT / I.MANIFEST_RELPATH
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def manifest():
    return I.load_manifest(ROOT)


# ------------------------------------------------- current tree vs manifest --


def test_current_source_tree_matches_the_v2_6_manifest():
    assert I.verify(ROOT) == []


def test_manifest_lists_exactly_the_files_in_scope(manifest):
    assert sorted(manifest["files"]) == I.walk_scope(ROOT)
    assert manifest["files"]  # not vacuous


def test_manifest_is_not_inside_its_own_scope():
    assert not I.MANIFEST_RELPATH.startswith(tuple(f"{b}/" for b in I.SCOPE))


# -------------------------------------------------- manifest format / rules --


def test_manifest_file_is_canonical_utf8_lf_and_deterministic(manifest):
    raw = MANIFEST.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    text = raw.decode("utf-8")  # raises if not UTF-8
    assert text == I.render(json.loads(text)), "manifest must equal its canonical rendering (sorted keys, 2-space indent)"
    assert I.render(I.build_manifest(ROOT)) == text, "regenerating from the tree must reproduce the committed manifest byte-for-byte"
    assert I.render(I.build_manifest(ROOT)) == I.render(I.build_manifest(ROOT))  # stable across runs


def test_manifest_uses_sha256_sorted_relative_paths_and_no_machine_specific_data(manifest):
    assert manifest["hashing"]["algorithm"] == "sha256"
    for group in (manifest["files"], manifest["historical_manifest_sha256"]):
        assert list(group) == sorted(group)
        for path, sha in group.items():
            assert HEX64.match(sha), path
            assert not path.startswith("/") and ":" not in path and "\\" not in path and ".." not in path.split("/"), path
    changes = manifest["v2_6_changes_from_v1_snapshot"]
    for paths in changes.values():
        assert paths == sorted(paths)
    blob = json.dumps(manifest).lower()
    for forbidden in ("timestamp", "generated_at", "created_at", "c:\\\\", "/home/", "/users/", "/tmp/"):
        assert forbidden not in blob, forbidden


# --------------------------------------- historical manifests stay immutable --


def test_historical_v2_3_v2_4_v2_5_manifests_are_unchanged(manifest):
    assert sorted(manifest["historical_manifest_sha256"]) == sorted(I.HISTORICAL_MANIFEST_FILES)
    for rel, sha in manifest["historical_manifest_sha256"].items():
        assert I.normalized_sha256(ROOT / rel) == sha, f"{rel} (a historical manifest) was modified"


def test_v2_3_v2_4_v2_5_recorded_the_same_v1_snapshot():
    assert I.historical_snapshots_agree(ROOT)


def test_declared_v2_6_changes_are_exactly_the_real_difference_from_the_v1_snapshot(manifest):
    """Nothing undeclared changed, and nothing declared is fictitious."""
    assert manifest["v2_6_changes_from_v1_snapshot"] == I.diff_from_historical(ROOT)


def test_v2_6_did_not_touch_the_v1_intelligence_engine_or_risk_code(manifest):
    declared = [p for paths in manifest["v2_6_changes_from_v1_snapshot"].values() for p in paths]
    assert declared
    assert not [p for p in declared if p.startswith("backend/app/intelligence/")]
    assert not [p for p in declared if p.startswith("backend/app/auth/")]  # authentication/authorization behaviour unchanged
    recorded = I.historical_snapshot(ROOT)
    assert any(k.startswith("backend/app/intelligence/") for k in recorded)
    for k in recorded:
        if k.startswith(("backend/app/intelligence/", "backend/app/auth/", "backend/app/db/")):
            assert I.raw_sha256(ROOT / k) == recorded[k], k


# ------------------------------------------- frozen_diff (historical tests) --


def _groups():
    recorded = {"v1_intelligence_source": {"intelligence/a.py": "1"}, I.HISTORICAL_GROUP: {"src/App.tsx": "old", "src/keep.ts": "same"}}
    now = {"v1_intelligence_source": {"intelligence/a.py": "1"}, I.HISTORICAL_GROUP: {"src/App.tsx": "new", "src/keep.ts": "same", "src/new.ts": "x"}}
    return recorded, now


def _decl(modified=(), added=(), removed=()):
    return {"v2_6_changes_from_v1_snapshot": {"modified": list(modified), "added": list(added), "removed": list(removed)}}


def test_frozen_diff_tolerates_only_declared_v2_6_application_files():
    recorded, now = _groups()
    assert I.frozen_diff(recorded, now, _decl(modified=["src/App.tsx"], added=["src/new.ts"])) == {}


def test_frozen_diff_still_reports_undeclared_application_changes():
    recorded, now = _groups()
    assert I.frozen_diff(recorded, now, _decl(modified=["src/App.tsx"])) == {I.HISTORICAL_GROUP: ["src/new.ts"]}
    assert I.frozen_diff(recorded, now, _decl()) == {I.HISTORICAL_GROUP: ["src/App.tsx", "src/new.ts"]}


def test_frozen_diff_never_relaxes_any_other_group():
    recorded, now = _groups()
    now["v1_intelligence_source"]["intelligence/a.py"] = "tampered"
    declared_everything = _decl(modified=["src/App.tsx", "intelligence/a.py"], added=["src/new.ts"])
    assert I.frozen_diff(recorded, now, declared_everything) == {"v1_intelligence_source": ["intelligence/a.py"]}


# --------------------------------------------------------- tamper detection --


@pytest.fixture
def tree_copy(tmp_path):
    """A scratch copy of the in-scope source plus the historical manifests; the real tree is never touched."""
    for base in I.SCOPE:
        shutil.copytree(ROOT / base, tmp_path / base, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for rel in (*I.HISTORICAL_MANIFEST_FILES, I.MANIFEST_RELPATH):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, tmp_path / rel)
    return tmp_path


def test_copy_of_the_tree_verifies(tree_copy):
    assert I.verify(tree_copy) == []


def test_modified_file_is_detected(tree_copy):
    target = tree_copy / "src/App.tsx"
    target.write_bytes(target.read_bytes() + b"\n// tampered\n")
    assert I.verify(tree_copy) == ["modified: src/App.tsx"]


def test_missing_and_extra_files_are_detected(tree_copy):
    (tree_copy / "src/api/types.ts").unlink()
    (tree_copy / "src/extra.ts").write_text("export {};\n", encoding="utf-8")
    assert I.verify(tree_copy) == ["missing: src/api/types.ts", "unexpected (not in V2.6 manifest): src/extra.ts"]


def test_tampered_historical_manifest_is_detected(tree_copy):
    rel = I.HISTORICAL_MANIFEST_FILES[1]
    (tree_copy / rel).write_bytes((tree_copy / rel).read_bytes() + b" ")
    assert I.verify(tree_copy) == [f"historical manifest changed: {rel}"]


def test_crlf_checkout_still_verifies(tree_copy):
    """A Windows checkout with core.autocrlf rewrites line endings; the manifest must not care."""
    for rel in I.walk_scope(tree_copy):
        p = tree_copy / rel
        p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert I.verify(tree_copy) == []

"""
V2.6 source-integrity tests.

V2.6 is an intentional evolution of backend/app/** and src/** after the frozen
V2.3-V2.5 evaluation runs. This file verifies the CURRENT source tree against the
V2.6 manifest (backend/v2_6_source_manifest.json), and checks that the historical
manifests recorded by V2.3/V2.4/V2.5 are intact and are accounted for exactly.
See backend/v2_6_integrity.py for the rationale.

Source changes made AFTER V2.6 are declared in the append-only ledger
backend/post_v2_6_changes.json (see test_post_v2_6_integrity.py); the V2.6 manifest itself is
immutable and `--write` refuses to rewrite it once the ledger exists. "The tree" below therefore
means the EFFECTIVE manifest: the V2.6 manifest plus the declared ledger changes. The historical
V2.3-V2.5 manifests and artifacts are never regenerated.
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
    # Effective manifest = V2.6 manifest + declared post-V2.6 changes. Every V2.6 file is still in it.
    effective = I.effective_manifest(ROOT)
    assert sorted(effective["files"]) == I.walk_scope(ROOT)
    assert set(manifest["files"]) <= set(effective["files"])
    assert manifest["files"]  # not vacuous


def test_manifest_is_not_inside_its_own_scope():
    assert not I.MANIFEST_RELPATH.startswith(tuple(f"{b}/" for b in I.SCOPE))


# -------------------------------------------------- manifest format / rules --


def test_manifest_file_is_canonical_utf8_lf_and_deterministic(manifest):
    raw = MANIFEST.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    text = raw.decode("utf-8")  # raises if not UTF-8
    assert text == I.render(json.loads(text)), "manifest must equal its canonical rendering (sorted keys, 2-space indent)"
    # The V2.6 manifest is immutable, so the tree is regenerated and compared with the EFFECTIVE manifest
    # (V2.6 manifest + declared post-V2.6 ledger changes); the V2.6 file's own bytes are pinned by the ledger.
    assert I.render(I.build_manifest(ROOT)) == I.render(I.effective_manifest(ROOT)), "regenerating from the tree must reproduce the effective manifest byte-for-byte"
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
    """Nothing undeclared changed, and nothing declared is fictitious (V2.6 declarations + ledger declarations)."""
    assert I.declared_changes_from_v1(ROOT) == I.diff_from_historical(ROOT)
    # the V2.6 declarations are a subset of that: V2.6's own list is never rewritten
    for kind, paths in manifest["v2_6_changes_from_v1_snapshot"].items():
        assert set(paths) <= set(I.declared_changes_from_v1(ROOT)[kind])


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
    for rel in (*I.HISTORICAL_MANIFEST_FILES, I.MANIFEST_RELPATH, I.LEDGER_RELPATH):
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


# ------------------------------------- git-ignored, local-only exclusion --
# The historical V2.3-V2.5 runs walked the filesystem and recorded one git-ignored file that no
# clean checkout contains. The V2.6 manifest excludes exactly that path. These tests keep the
# exclusion from silently widening: every excluded path must be git-ignored AND referenced by no
# source file, and the historical manifests must still record it, unchanged.


def test_exclusion_list_is_exactly_the_one_known_local_only_path():
    # Adding to this tuple weakens the integrity check; do it only deliberately, with the two tests below passing.
    assert I.EXCLUDED_LOCAL_ONLY_PATHS == ("src/imports/pasted_text/",)


def test_every_excluded_path_is_git_ignored():
    ignored = {line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    for prefix in I.EXCLUDED_LOCAL_ONLY_PATHS:
        assert prefix in ignored, f"{prefix} is excluded from the manifest but is not listed in .gitignore"


def test_no_source_file_references_an_excluded_path():
    needles = ("pasted_text", "pasted-attachment")
    candidates = [ROOT / rel for rel in I.walk_scope(ROOT)]
    candidates += [ROOT / "vite.config.ts", ROOT / "index.html", ROOT / "package.json", ROOT / "tsconfig.json"]
    candidates += [p for base in ("scripts", "intelligence") for p in (ROOT / base).rglob("*") if p.suffix in {".py", ".mjs", ".ts"}]
    offenders = [str(p.relative_to(ROOT)) for p in candidates if p.is_file() and any(n in p.read_text(encoding="utf-8", errors="ignore") for n in needles)]
    assert offenders == []


def test_manifest_records_the_exclusion_and_has_no_entry_for_excluded_paths(manifest):
    assert manifest["excluded_local_only_paths"] == list(I.EXCLUDED_LOCAL_ONLY_PATHS)
    assert not [p for p in manifest["files"] if I.is_excluded(p)]


def test_historical_manifests_still_record_the_excluded_file_unchanged():
    """We exclude the path from V2.6 verification only; V2.3/V2.4/V2.5 history is untouched."""
    for rel in I.HISTORICAL_MANIFEST_FILES:
        group = json.loads((ROOT / rel).read_text(encoding="utf-8"))["frozen_manifest"][I.HISTORICAL_GROUP]
        assert "src/imports/pasted_text/pasted-attachment.txt" in group, rel


def test_verify_reports_a_mismatch_between_manifest_and_tool_exclusion_lists(manifest):
    problems = I.verify(ROOT, {**manifest, "excluded_local_only_paths": []})
    assert "excluded_local_only_paths in the manifest differs from the tool's exclusion list" in problems


def test_excluded_file_being_present_or_absent_does_not_matter(tree_copy):
    target = tree_copy / "src/imports/pasted_text/pasted-attachment.txt"
    if target.exists():
        target.unlink()
    assert I.verify(tree_copy) == []  # a clean clone: file absent
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("anything at all\r\n", encoding="utf-8")
    assert I.verify(tree_copy) == []  # a developer machine: file present, contents irrelevant
    assert not [p for p in I.walk_scope(tree_copy) if I.is_excluded(p)]


def test_exclusion_does_not_cover_other_paths_in_the_same_folder_tree(tree_copy):
    sibling = tree_copy / "src/imports/other_notes.txt"
    sibling.parent.mkdir(parents=True, exist_ok=True)
    sibling.write_text("x\n", encoding="utf-8")
    assert I.verify(tree_copy) == ["unexpected (not in V2.6 manifest): src/imports/other_notes.txt"]


def test_frozen_diff_tolerates_only_the_excluded_path_being_absent():
    recorded = {I.HISTORICAL_GROUP: {"src/keep.ts": "same", "src/imports/pasted_text/pasted-attachment.txt": "h"}}
    now = {I.HISTORICAL_GROUP: {"src/keep.ts": "same"}}
    assert I.frozen_diff(recorded, now, _decl()) == {}
    # any other missing file is still reported
    now_missing_other = {I.HISTORICAL_GROUP: {}}
    assert I.frozen_diff(recorded, now_missing_other, _decl()) == {I.HISTORICAL_GROUP: ["src/keep.ts"]}
    # a similarly named path elsewhere is not excused
    recorded2 = {I.HISTORICAL_GROUP: {"src/imports/other.txt": "h"}}
    assert I.frozen_diff(recorded2, {I.HISTORICAL_GROUP: {}}, _decl()) == {I.HISTORICAL_GROUP: ["src/imports/other.txt"]}


def test_frozen_diff_never_excuses_the_excluded_path_in_other_groups():
    recorded = {"v2_1_dataset_and_spec": {"src/imports/pasted_text/pasted-attachment.txt": "h"}}
    assert I.frozen_diff(recorded, {"v2_1_dataset_and_spec": {}}, _decl()) == {
        "v2_1_dataset_and_spec": ["src/imports/pasted_text/pasted-attachment.txt"]
    }


# -------------------------------- line endings are not content (CI regression) --
# The historical manifests recorded RAW hashes of a Windows working tree. src/pages/UsersPage.tsx had
# CRLF line endings there while its git blob has LF, so a Linux/CI checkout (LF) hashed differently and
# was falsely reported as a V2.6 change. Content is compared modulo line endings; content changes are
# still detected.

USERS_PAGE = "src/pages/UsersPage.tsx"


def _rewrite_line_endings(path, ending):
    data = path.read_bytes().replace(b"\r\n", b"\n")
    path.write_bytes(data if ending == "lf" else data.replace(b"\n", b"\r\n"))


@pytest.mark.parametrize("ending", ["lf", "crlf"])
def test_line_endings_alone_never_count_as_a_change_from_the_v1_snapshot(tree_copy, manifest, ending):
    _rewrite_line_endings(tree_copy / USERS_PAGE, ending)  # e.g. what a Linux checkout of an LF blob looks like
    changes = I.diff_from_historical(tree_copy)
    assert USERS_PAGE not in changes["modified"]
    assert changes == I.declared_changes_from_v1(tree_copy)
    assert I.verify(tree_copy) == []


@pytest.mark.parametrize("ending", ["lf", "crlf"])
def test_a_real_content_change_is_still_detected_whatever_the_line_endings(tree_copy, ending):
    _rewrite_line_endings(tree_copy / USERS_PAGE, ending)
    target = tree_copy / USERS_PAGE
    text = target.read_bytes().decode("utf-8")
    target.write_bytes(text.replace("export default", "export  default", 1).encode("utf-8"))  # a one-character content change
    assert USERS_PAGE in I.diff_from_historical(tree_copy)["modified"]
    assert f"modified: {USERS_PAGE}" in I.verify(tree_copy)


def test_every_file_in_the_v1_snapshot_is_recognised_as_unchanged_or_declared():
    """The real tree: the only 'modified' files are the declared V2.6 ones — none is a line-ending artefact."""
    assert I.diff_from_historical(ROOT)["modified"] == I.declared_changes_from_v1(ROOT)["modified"]


def test_frozen_diff_ignores_line_endings_in_the_v1_group_only(tree_copy):
    _rewrite_line_endings(tree_copy / USERS_PAGE, "crlf")
    recorded_crlf_hash = I.raw_sha256(tree_copy / USERS_PAGE)
    _rewrite_line_endings(tree_copy / USERS_PAGE, "lf")  # the checkout now has LF
    lf_hash = I.raw_sha256(tree_copy / USERS_PAGE)
    assert recorded_crlf_hash != lf_hash
    recorded = {I.HISTORICAL_GROUP: {USERS_PAGE: recorded_crlf_hash}}
    now = {I.HISTORICAL_GROUP: {USERS_PAGE: lf_hash}}
    assert I.frozen_diff(recorded, now, _decl(), root=tree_copy) == {}  # same content, only line endings differ
    # ...but any other group stays byte-exact (V2.1-V2.5 evaluation guarantees are not relaxed)
    other = {"v2_2_metrics_and_reference_outputs": {USERS_PAGE: recorded_crlf_hash}}
    assert I.frozen_diff(other, {"v2_2_metrics_and_reference_outputs": {USERS_PAGE: lf_hash}}, _decl(), root=tree_copy) == {
        "v2_2_metrics_and_reference_outputs": [USERS_PAGE]
    }
    # ...and a content change in the V1 group is still reported
    target = tree_copy / USERS_PAGE
    target.write_bytes(target.read_bytes() + b"// changed\n")
    changed = {I.HISTORICAL_GROUP: {USERS_PAGE: I.raw_sha256(target)}}
    assert I.frozen_diff(recorded, changed, _decl(), root=tree_copy) == {I.HISTORICAL_GROUP: [USERS_PAGE]}


def test_line_ending_variants_cover_text_files_only(tmp_path):
    import hashlib

    def sha(b):
        return hashlib.sha256(b).hexdigest()

    text = tmp_path / "a.ts"
    for stored in (b"x\r\ny\r\n", b"x\ny\n"):  # the same content stored with either line ending
        text.write_bytes(stored)
        assert I.sha256_line_ending_variants(text) == {sha(b"x\r\ny\r\n"), sha(b"x\ny\n")}
    text.write_bytes(b"x\ny\nz\n")  # different content is never in the other file's variant set
    assert not I.sha256_line_ending_variants(text) & {sha(b"x\r\ny\r\n"), sha(b"x\ny\n")}
    binary = tmp_path / "a.bin"
    binary.write_bytes(b"x\r\ny\r\n")
    assert I.sha256_line_ending_variants(binary) == {sha(b"x\r\ny\r\n")}  # binary content is never normalised

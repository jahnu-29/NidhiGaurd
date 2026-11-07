"""
Post-V2.6 integrity tests (the layered design).

  Layer 1  backend/v2_6_source_manifest.json   immutable; its SHA-256 is pinned by the ledger
  Layer 2  backend/post_v2_6_changes.json      append-only, hash-chained ledger of later changes
  Layer 3  the current tree must equal Layer 1 + Layer 2 exactly (the "effective" manifest)

Every tamper test runs on a scratch copy of the tree; the real repository is never modified.
"""

from __future__ import annotations

import copy
import json
import shutil

import pytest

from backend import v2_6_integrity as I

ROOT = I.repo_root()

PHASE_2_1_MODIFIED = (
    "backend/app/api/dependencies.py",
    "backend/app/ingestion/csv_ingestion.py",
    "backend/app/main.py",
)
PHASE_2_1_ADDED = ("backend/app/intelligence/cache.py",)
PHASE_2_1_FILES = (*PHASE_2_1_MODIFIED, *PHASE_2_1_ADDED)


# ------------------------------------------------------------------ helpers --


@pytest.fixture
def scratch(tmp_path):
    """A scratch copy of the in-scope source, the historical manifests, the V2.6 manifest and the ledger."""
    for base in I.SCOPE:
        shutil.copytree(ROOT / base, tmp_path / base, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for rel in (*I.HISTORICAL_MANIFEST_FILES, I.MANIFEST_RELPATH, I.LEDGER_RELPATH):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, tmp_path / rel)
    return tmp_path


def read_ledger(root):
    return json.loads((root / I.LEDGER_RELPATH).read_text(encoding="utf-8"))


def write_ledger(root, ledger, rechain=True):
    """Write a ledger; with rechain=True its digests/links are recomputed so ONLY the semantic edit is under test."""
    if rechain:
        previous = ledger["v2_6_manifest"]["sha256"]
        for entry in ledger["changes"]:
            entry["previous_entry_sha256"] = previous
            entry["entry_sha256"] = I.entry_digest(entry)
            previous = entry["entry_sha256"]
    (root / I.LEDGER_RELPATH).write_bytes(I.render(ledger).encode("utf-8"))


def append(path, text="\n# tampered\n"):
    p = path
    p.write_bytes(p.read_bytes() + text.encode("utf-8"))


def entry_files(ledger, entry_index):
    return {f["path"]: f for f in ledger["changes"][entry_index]["files"]}


# ----------------------------------------------- 1. Layer 1 is pinned (and 15) --


def test_historical_v2_6_manifest_hash_is_pinned_in_the_ledger():
    ledger = I.load_ledger(ROOT)
    assert ledger["v2_6_manifest"]["path"] == I.MANIFEST_RELPATH
    assert ledger["v2_6_manifest"]["sha256"] == I.normalized_sha256(ROOT / I.MANIFEST_RELPATH)
    assert ledger["changes"][0]["previous_entry_sha256"] == ledger["v2_6_manifest"]["sha256"]  # chain anchored to it


def test_the_v2_6_manifest_is_not_rewritten_by_the_ledger():
    manifest = I.load_manifest(ROOT)
    # still the V2.6 content: V2.6's own declared change list is untouched, and main.py still has the V2.6 hash
    assert len(manifest["v2_6_changes_from_v1_snapshot"]["modified"]) == 6
    assert "backend/app/main.py" not in manifest["v2_6_changes_from_v1_snapshot"]["modified"]
    assert "backend/app/intelligence/cache.py" not in manifest["files"]
    assert manifest["files"]["backend/app/main.py"] == I.load_ledger(ROOT)["changes"][0]["files"][0]["base_sha256"]


def test_tampering_with_the_historical_v2_6_manifest_fails(scratch):
    target = scratch / I.MANIFEST_RELPATH
    manifest = json.loads(target.read_text(encoding="utf-8"))
    manifest["files"]["src/App.tsx"] = "0" * 64  # e.g. quietly re-blessing a file
    target.write_bytes(I.render(manifest).encode("utf-8"))
    assert f"historical V2.6 manifest changed: {I.MANIFEST_RELPATH}" in I.verify(scratch)


def test_regenerating_the_v2_6_manifest_to_absorb_changes_fails(scratch):
    """What `--write` used to do: bake the current tree into the V2.6 manifest. The pin catches it."""
    (scratch / I.MANIFEST_RELPATH).write_bytes(I.render(I.build_manifest(scratch)).encode("utf-8"))
    assert f"historical V2.6 manifest changed: {I.MANIFEST_RELPATH}" in I.verify(scratch)


def test_tampering_with_a_v2_3_v2_4_v2_5_manifest_fails(scratch):
    rel = I.HISTORICAL_MANIFEST_FILES[0]
    append(scratch / rel, " ")
    assert I.verify(scratch) == [f"historical manifest changed: {rel}"]


# ------------------------------------------- 2. chain / base hashes are valid --


def test_ledger_chain_and_base_hashes_are_valid():
    effective, problems, changes = I.apply_ledger(ROOT)
    assert problems == []
    ledger = I.load_ledger(ROOT)
    previous = ledger["v2_6_manifest"]["sha256"]
    for entry in ledger["changes"]:
        assert entry["previous_entry_sha256"] == previous
        assert entry["entry_sha256"] == I.entry_digest(entry)
        previous = entry["entry_sha256"]
    assert I.render(ledger) == (ROOT / I.LEDGER_RELPATH).read_bytes().decode("utf-8")  # canonical rendering
    assert len(changes) == 5


def test_ledger_declares_exactly_the_cors_change_and_phase_2_1():
    ledger = I.load_ledger(ROOT)
    cors, phase = ledger["changes"]
    assert [(f["path"], f["change"]) for f in cors["files"]] == [("backend/app/main.py", "modified")]
    assert {(f["path"], f["change"]) for f in phase["files"]} == {
        *((p, "modified") for p in PHASE_2_1_MODIFIED),
        *((p, "added") for p in PHASE_2_1_ADDED),
    }
    # main.py is chained: the Phase 2.1 base is the CORS result, which itself is based on the V2.6 hash
    manifest = I.load_manifest(ROOT)
    assert cors["files"][0]["base_sha256"] == manifest["files"]["backend/app/main.py"]
    assert entry_files(ledger, 1)["backend/app/main.py"]["base_sha256"] == cors["files"][0]["sha256"]
    assert entry_files(ledger, 1)["backend/app/intelligence/cache.py"]["base_sha256"] is None
    for f in (*cors["files"], *phase["files"]):
        if f["change"] == "modified":
            assert f["base_sha256"] != f["sha256"]


def test_only_the_declared_files_differ_from_the_v2_6_manifest():
    """No silent extras: the effective manifest differs from V2.6 in exactly the five ledger-declared paths."""
    manifest = I.load_manifest(ROOT)
    effective = I.effective_manifest(ROOT)["files"]
    changed = {p for p in effective if manifest["files"].get(p) != effective[p]}
    assert changed == set(PHASE_2_1_FILES)
    assert set(manifest["files"]) - set(effective) == set()  # nothing removed


# ------------------------------ 3 / 14 / 17. effective manifest == current tree --


def test_effective_manifest_matches_the_current_tree():
    assert I.verify(ROOT) == []
    effective = I.effective_manifest(ROOT)
    for rel, sha in effective["files"].items():
        assert I.normalized_sha256(ROOT / rel) == sha, rel


def test_effective_manifest_has_no_unexpected_or_missing_files():
    assert sorted(I.effective_manifest(ROOT)["files"]) == I.walk_scope(ROOT)


def test_declared_phase_2_1_files_pass_when_hashes_match(scratch):
    assert I.verify(scratch) == []
    ledger = read_ledger(scratch)
    for f in ledger["changes"][1]["files"]:
        assert I.normalized_sha256(scratch / f["path"]) == f["sha256"], f["path"]


def test_crlf_checkout_of_declared_files_still_verifies(scratch):
    for rel in PHASE_2_1_FILES:
        p = scratch / rel
        p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert I.verify(scratch) == []


# ------------------------------------------------ 4 / 5 / 6. undeclared changes --


def test_undeclared_modification_fails(scratch):
    append(scratch / "src/App.tsx")
    assert I.verify(scratch) == ["modified: src/App.tsx"]


def test_undeclared_added_file_fails(scratch):
    (scratch / "backend/app/intelligence/sneaky.py").write_text("x = 1\n", encoding="utf-8")
    (scratch / "src/extra.ts").write_text("export {};\n", encoding="utf-8")
    assert I.verify(scratch) == [
        "unexpected (not in V2.6 manifest): backend/app/intelligence/sneaky.py",
        "unexpected (not in V2.6 manifest): src/extra.ts",
    ]


def test_undeclared_deletion_fails(scratch):
    (scratch / "src/api/types.ts").unlink()
    assert I.verify(scratch) == ["missing: src/api/types.ts"]


def test_deleting_a_declared_phase_2_1_file_fails(scratch):
    (scratch / "backend/app/intelligence/cache.py").unlink()
    assert I.verify(scratch) == ["missing: backend/app/intelligence/cache.py"]


def test_deleting_a_protected_v1_file_fails(scratch):
    (scratch / "backend/app/intelligence/db_data_loader.py").unlink()
    assert I.verify(scratch) == ["missing: backend/app/intelligence/db_data_loader.py"]


# -------------------------------- 11 / 12 / 13. later edits need a new entry --


@pytest.mark.parametrize("rel", PHASE_2_1_FILES)
def test_later_modification_of_a_declared_file_without_a_new_ledger_entry_fails(scratch, rel):
    """cache.py, dependencies.py, csv_ingestion.py and main.py are pinned: a further edit is not accepted."""
    append(scratch / rel)
    assert I.verify(scratch) == [f"modified: {rel}"]


def test_later_modification_of_main_py_is_not_excused_by_the_cors_entry_alone(scratch):
    """main.py's CORS hash is only the intermediate state; the tree must equal the LATEST declared hash."""
    ledger = read_ledger(scratch)
    ledger["changes"].pop()  # pretend Phase 2.1 was never declared
    write_ledger(scratch, ledger)
    assert "modified: backend/app/main.py" in I.verify(scratch)  # main.py now differs from the CORS-only state


# -------------------------------------- 7 / 8. wrong hash, wrong base hash --


def test_declared_modification_with_wrong_new_hash_fails(scratch):
    ledger = read_ledger(scratch)
    entry_files(ledger, 1)["backend/app/api/dependencies.py"]["sha256"] = "f" * 64
    write_ledger(scratch, ledger)  # chain stays valid: only the declared hash is wrong
    assert I.verify(scratch) == ["modified: backend/app/api/dependencies.py"]


def test_declared_added_file_with_wrong_hash_fails(scratch):
    ledger = read_ledger(scratch)
    entry_files(ledger, 1)["backend/app/intelligence/cache.py"]["sha256"] = "e" * 64
    write_ledger(scratch, ledger)
    assert I.verify(scratch) == ["modified: backend/app/intelligence/cache.py"]


def test_declared_modification_with_wrong_base_hash_fails(scratch):
    ledger = read_ledger(scratch)
    entry_files(ledger, 1)["backend/app/api/dependencies.py"]["base_sha256"] = "d" * 64
    write_ledger(scratch, ledger)
    problems = I.verify(scratch)
    assert any("dependencies.py: base_sha256 does not equal the effective hash before this change" in p for p in problems)


def test_phase_2_1_main_py_entry_must_be_based_on_the_cors_hash_not_the_v2_6_hash(scratch):
    ledger = read_ledger(scratch)
    v2_6_hash = I.load_manifest(ROOT)["files"]["backend/app/main.py"]
    entry_files(ledger, 1)["backend/app/main.py"]["base_sha256"] = v2_6_hash  # skips the CORS step
    write_ledger(scratch, ledger)
    assert any("backend/app/main.py: base_sha256 does not equal the effective hash" in p for p in I.verify(scratch))


def test_an_added_entry_must_have_a_null_base_and_must_not_already_exist(scratch):
    ledger = read_ledger(scratch)
    entry_files(ledger, 1)["backend/app/intelligence/cache.py"]["base_sha256"] = "c" * 64
    write_ledger(scratch, ledger)
    assert any("an added file must have base_sha256 null" in p for p in I.verify(scratch))
    ledger = read_ledger(scratch)
    ledger["changes"][1]["files"].append({"path": "src/App.tsx", "change": "added", "base_sha256": None, "sha256": "a" * 64})
    ledger["changes"][1]["files"].sort(key=lambda f: f["path"])
    write_ledger(scratch, ledger)
    assert any("src/App.tsx: an added file must have base_sha256 null and must not already exist" in p for p in I.verify(scratch))


# -------------------------------------------------------- 9. forbidden paths --


def _declare(scratch, path, change, base=None):
    ledger = read_ledger(scratch)
    ledger["changes"].append(
        {
            "id": "post-v2.6-999-test",
            "description": "forbidden-path test",
            "previous_entry_sha256": "",
            "files": [{"path": path, "change": change, "base_sha256": base, "sha256": "9" * 64}],
        }
    )
    write_ledger(scratch, ledger)


@pytest.mark.parametrize(
    "path,change",
    [
        ("intelligence/risk_engine.py", "modified"),  # V1 intelligence engine
        ("evaluation/evaluation_report.json", "modified"),  # evaluation artifacts
        ("backend/app/auth/security.py", "modified"),  # V1 auth
        ("backend/app/auth/brand_new.py", "added"),  # no new auth code through the ledger either
        ("backend/app/db/models.py", "modified"),  # V1 db
        ("backend/app/intelligence/db_data_loader.py", "modified"),  # V1 file inside the intelligence adapter package
        ("backend/v2_6_integrity.py", "added"),  # outside the verified scope
        ("src/imports/pasted_text/pasted-attachment.txt", "added"),  # local-only excluded path
        ("../outside.py", "added"),
    ],
)
def test_declaring_a_forbidden_path_in_the_ledger_fails(scratch, path, change):
    base = I.load_manifest(ROOT)["files"].get(path) if change == "modified" else None
    _declare(scratch, path, change, base)
    problems = I.verify(scratch)
    assert any(f"{path}:" in p and "post-v2.6-999-test" in p for p in problems) or any(path in p for p in problems), problems
    assert problems  # never silently accepted


def test_forbidden_paths_are_not_tolerated_by_the_historical_freeze_check(scratch):
    _declare(scratch, "backend/app/auth/brand_new.py", "added")
    (scratch / "backend/app/auth/brand_new.py").write_text("x = 1\n", encoding="utf-8")
    assert I.ledger_tolerated_paths(scratch) == set()


def test_ledger_may_add_a_new_file_next_to_the_v1_intelligence_adapter():
    """cache.py is allowed (a NEW file); the V1 files beside it are not."""
    assert "backend/app/intelligence/cache.py" in I.effective_manifest(ROOT)["files"]
    v1 = I.historical_snapshot(ROOT)
    assert "backend/app/intelligence/cache.py" not in v1
    assert I.verify(ROOT) == []


# ------------------------------------------------------ 16. ledger tampering --


def test_editing_an_existing_ledger_entry_without_rechaining_fails(scratch):
    ledger = read_ledger(scratch)
    ledger["changes"][0]["description"] = "rewritten history"
    write_ledger(scratch, ledger, rechain=False)
    problems = I.verify(scratch)
    assert any("entry #1" in p and "entry_sha256 does not match its content" in p for p in problems)


def test_rewriting_an_earlier_entry_even_with_a_valid_own_digest_breaks_the_chain(scratch):
    ledger = read_ledger(scratch)
    ledger["changes"][0]["description"] = "rewritten history"
    ledger["changes"][0]["entry_sha256"] = I.entry_digest(ledger["changes"][0])  # forged digest for entry 1 only
    write_ledger(scratch, ledger, rechain=False)
    problems = I.verify(scratch)
    assert any("entry #2" in p and "previous_entry_sha256 does not chain" in p for p in problems)


def test_reordering_ledger_entries_fails(scratch):
    ledger = read_ledger(scratch)
    ledger["changes"].reverse()
    write_ledger(scratch, ledger, rechain=False)
    problems = I.verify(scratch)
    assert any("previous_entry_sha256 does not chain" in p for p in problems)
    assert any("base_sha256 does not equal the effective hash" in p or "must not already exist" in p for p in problems)


def test_removing_a_ledger_entry_fails(scratch):
    ledger = read_ledger(scratch)
    del ledger["changes"][0]  # drop the CORS entry, keep Phase 2.1
    write_ledger(scratch, ledger, rechain=False)
    assert I.verify(scratch)


def test_ledger_with_a_duplicate_entry_id_or_unsorted_files_fails(scratch):
    ledger = read_ledger(scratch)
    ledger["changes"][1]["id"] = ledger["changes"][0]["id"]
    write_ledger(scratch, ledger)
    assert any("missing or duplicate id" in p for p in I.verify(scratch))
    ledger = read_ledger(scratch)
    ledger["changes"][1]["files"].reverse()
    write_ledger(scratch, ledger)
    assert any("files must be sorted by path" in p for p in I.verify(scratch))


def test_malformed_or_missing_ledger_fields_fail_instead_of_crashing(scratch):
    ledger = read_ledger(scratch)
    ledger["v2_6_manifest"]["sha256"] = "not-a-hash"
    write_ledger(scratch, ledger, rechain=False)
    assert any("pin is malformed" in p for p in I.verify(scratch))
    (scratch / I.LEDGER_RELPATH).write_text("{not json", encoding="utf-8")
    assert any("ledger unreadable" in p for p in I.verify(scratch))


# --------------------------------------------------------------- 10. --write --


def test_write_refuses_when_the_ledger_exists(monkeypatch, capsys, scratch):
    before = {rel: (scratch / rel).read_bytes() for rel in (I.MANIFEST_RELPATH, I.LEDGER_RELPATH)}
    monkeypatch.setattr(I, "repo_root", lambda: scratch)
    assert I.main(["--write"]) == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err and "ledger" in err and "Nothing was written" in err
    assert {rel: (scratch / rel).read_bytes() for rel in before} == before  # no file modified


def test_write_on_the_real_repository_refuses_and_modifies_nothing(capsys):
    before = (ROOT / I.MANIFEST_RELPATH).read_bytes(), (ROOT / I.LEDGER_RELPATH).read_bytes()
    assert I.main(["--write"]) == 2
    assert "REFUSED" in capsys.readouterr().err
    assert ((ROOT / I.MANIFEST_RELPATH).read_bytes(), (ROOT / I.LEDGER_RELPATH).read_bytes()) == before


def test_write_is_only_refused_because_of_the_ledger(monkeypatch, scratch):
    """Without a ledger the original V2.6 behaviour is unchanged (the guard is not a blanket removal)."""
    (scratch / I.LEDGER_RELPATH).unlink()
    monkeypatch.setattr(I, "repo_root", lambda: scratch)
    assert I.main(["--write"]) == 0
    assert (scratch / I.MANIFEST_RELPATH).read_bytes() != (ROOT / I.MANIFEST_RELPATH).read_bytes()  # only in the scratch copy


def test_check_cli_passes_on_the_real_repository(capsys):
    assert I.main(["--check"]) == 0
    assert "OK" in capsys.readouterr().out


# ------------------------------------------- historical freeze (frozen_diff) --


def _v1_group(root):
    recorded = {I.HISTORICAL_GROUP: dict(I.historical_snapshot(root))}
    now = {I.HISTORICAL_GROUP: {rel: I.raw_sha256(root / rel) for rel in I.walk_scope(root)}}
    return recorded, now


def test_frozen_diff_accepts_exactly_the_declared_post_v2_6_changes(scratch):
    recorded, now = _v1_group(scratch)
    assert I.frozen_diff(recorded, now, root=scratch) == {}
    # ...and only because the ledger declares them: without the ledger the same files are reported
    (scratch / I.LEDGER_RELPATH).unlink()
    assert I.frozen_diff(recorded, now, root=scratch) == {I.HISTORICAL_GROUP: sorted(PHASE_2_1_FILES)}


@pytest.mark.parametrize("rel", PHASE_2_1_FILES)
def test_frozen_diff_reports_a_declared_file_whose_hash_no_longer_matches(scratch, rel):
    append(scratch / rel)
    recorded, now = _v1_group(scratch)
    assert I.frozen_diff(recorded, now, root=scratch) == {I.HISTORICAL_GROUP: [rel]}


def test_frozen_diff_still_reports_undeclared_changes_and_tolerates_nothing_when_the_ledger_is_invalid(scratch):
    append(scratch / "src/pages/DashboardPage.tsx")
    (scratch / "src/extra.ts").write_text("export {};\n", encoding="utf-8")
    recorded, now = _v1_group(scratch)
    assert I.frozen_diff(recorded, now, root=scratch) == {I.HISTORICAL_GROUP: ["src/extra.ts", "src/pages/DashboardPage.tsx"]}
    ledger = read_ledger(scratch)
    ledger["changes"][1]["description"] = "edited without rechaining"
    write_ledger(scratch, ledger, rechain=False)  # invalid ledger -> no post-V2.6 tolerance at all
    got = I.frozen_diff(recorded, now, root=scratch)[I.HISTORICAL_GROUP]
    assert set(PHASE_2_1_FILES) <= set(got)


def test_frozen_diff_never_relaxes_other_groups_for_ledger_paths(scratch):
    recorded, now = _v1_group(scratch)
    recorded["v2_2_metrics_and_reference_outputs"] = {"backend/app/main.py": "old"}
    now["v2_2_metrics_and_reference_outputs"] = {"backend/app/main.py": "new"}
    assert I.frozen_diff(recorded, now, root=scratch) == {"v2_2_metrics_and_reference_outputs": ["backend/app/main.py"]}


def test_frozen_diff_v2_6_allowance_is_still_the_historical_path_list(scratch):
    """The V2.6 allowance is unchanged: a V2.6-declared file is tolerated by path, not by the ledger."""
    recorded, now = _v1_group(scratch)
    append(scratch / "src/App.tsx")  # V2.6-declared in the V2.6 manifest: tolerated by path (any content), as before
    recorded, now = _v1_group(scratch)
    assert I.frozen_diff(recorded, now, root=scratch) == {}
    append(scratch / "src/pages/DashboardPage.tsx")  # NOT declared anywhere
    recorded, now = _v1_group(scratch)
    assert I.frozen_diff(recorded, now, root=scratch) == {I.HISTORICAL_GROUP: ["src/pages/DashboardPage.tsx"]}


def test_real_tree_has_no_v1_group_difference_beyond_the_declared_changes():
    recorded, now = _v1_group(ROOT)
    assert I.frozen_diff(recorded, now) == {}


def test_effective_manifest_refuses_to_build_from_an_invalid_ledger(scratch):
    ledger = read_ledger(scratch)
    ledger["changes"][0]["description"] = "x"
    write_ledger(scratch, ledger, rechain=False)
    with pytest.raises(ValueError):
        I.effective_manifest(scratch)


def test_ledger_fixture_isolation():
    """Guard against a test accidentally mutating the real ledger/manifest (they must equal git's committed bytes)."""
    import subprocess

    for rel in (I.MANIFEST_RELPATH,):
        committed = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True)
        if committed.returncode == 0:  # skipped when git metadata is unavailable
            assert (ROOT / rel).read_bytes().replace(b"\r\n", b"\n") == committed.stdout.replace(b"\r\n", b"\n")

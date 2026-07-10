# API Standardization Tracker — Canonical-Only Envelope + Release Versioning

**Status:** Planning (no code changes started)
**Owner:** Heather
**Created:** 2026-07-10
**Related docs:** `BreedBase_Files_Review.md`, `ClaudeCode_Prompt_Contract_Change_Impact_Map.md`, `Conformance_Test_Kit_Plan.md`, `Repo_Improvement_Tracker.md`

---

## Scope

Standardize the framework on a **single canonical output envelope** and formalize **release/contract/schema versioning**. Concretely, this task:

- Removes `output_mode` from the framework and reference pipeline (`app.py`, `process_image.py`, `cli.py`, `openapi.yml`).
- Removes the legacy BreedBase response path (`format=breedbase` / `_to_breedbase_legacy`) from mainline and moves pipeline-specific tuning (`marker_diameter_in`) out of the framework HTTP surface into the pipeline.
- Formalizes the canonical envelope as *the* standard, adds a runtime-assertable `schema_version`, and reconciles the endpoint path (`/upload` → `/analyze`).
- Updates the BreedBase consumer (`ImageAnalysis.pm`, `image_analysis.mas`) to parse the canonical envelope uniformly.
- Establishes SemVer releases (git tags + GitHub Releases + Docker tag parity) and documents the migration on the BreedBase wiki.

**Out of scope / handled operationally, not in the standard:** keeping uncontrolled legacy instances alive. That is covered by the already-frozen `v1.0.1` artifact (see Versioning Baseline) and is *not* a feature of the new contract. Self-hosted straggler pipelines are independent of this framework and age out on their own.

---

## What triggered this task

The contract-change impact map and the subsequent review of the BreedBase files (`ImageAnalysis.pm`, `image_analysis.mas`) surfaced that the framework is not yet "truly standard":

1. **Multiple output shapes.** `app.py` emits a canonical envelope by default but also a legacy BreedBase shape via `?format=breedbase` (`_to_breedbase_legacy`). Two shapes undermine the "one predictable format" promise.
2. **A redundant mode knob.** `output_mode` (`single`/`all`) does not change the schema — the canonical envelope already expresses single/multiple objects (`objects[]`) and single/multiple traits (`traits{}`). `output_mode` was POC scaffolding and adds confusion.
3. **Pipeline tuning leaked into the contract.** `marker_diameter_in` is a seed-pipeline calibration detail exposed as an HTTP parameter, blurring the framework/pipeline boundary.
4. **Spec/README/handler disagreements.** Path `/upload` (spec/handler) vs `/analyze` (README); `output_mode`/`format` documented as form fields (README) but read as query params (`app.py`). BreedBase actually sends only `image` as multipart and pins nothing — the path is config-driven (`server_endpoint`).
5. **Brittle consumer coupling.** BreedBase detects multi- vs single-trait via `exists objects[0].traits` and branches save logic on UI display-name strings, so the canonical default routes every response down the multi-trait path.

**Background:** the original integration returned a single trait only (now legacy). The framework was later expanded to single/multiple objects and single/multiple traits. A legacy output trigger was added so a few un-updatable BreedBase instances keep working. That trigger should live outside the standard, not inside mainline.

---

## Versioning Baseline (anchor point)

- **Legacy artifact already exists and is live:** Docker image `hkmanchi/sorghum-breedbase-image-pipeline:v1.0.1` was built, pulled, and is actively running on BreedBase. This is the frozen legacy artifact — it keeps serving the old shape to the instances on our infrastructure indefinitely, with no code maintenance.
- **Because `v1.0.1` is taken, versioning starts from there.** The canonical-only standard is a **breaking** change (removes `output_mode`/`format`), so it is released as **`v2.0.0`**.
- **Three independent version axes** (do not conflate):
  - **Release version** — SemVer on git tags / GitHub Releases / Docker image tags. Versions code + deployment. Legacy = `v1.0.1`; canonical-only = `v2.0.0`.
  - **`openapi.yml` `info.version`** — versions the transport contract (currently `"1.0"`; bump to `2.0.0` with the canonical-only spec).
  - **Envelope `schema_version`** (new field) + existing `pipeline.version` — versions the payload shape / pipeline; read at runtime by consumers. Proposed envelope `schema_version` start: `"1.0"` (first formalized canonical schema).
- **Retire `:latest`** for BreedBase use. Consumers must pin a version tag (`:v1.0.1`, `:v2.0.0`), never `:latest`.

> **Strategy note (Strategy A — freeze by version):** Freeze first, then clean. `v1.0.1` is the freeze; all legacy code is removed from mainline only after `v1.0.1` is confirmed immutable and documented.

---

## Proposed Strategy — Subtasks

Sequencing: **1 → 2** first (baseline + versioning), then **3–5** (framework changes), **6** (release), **7** (consumer), **8** (docs), **9** (verification). 3–5 can proceed in parallel branches but land together in `v2.0.0`.

---

### Subtask 1 — Formalize the frozen legacy baseline (`v1.0.1`)

- [ ] Status: Not started

**Purpose:** Lock the already-running legacy image to an immutable, documented git reference so it can serve uncontrolled stragglers forever without maintenance, before any legacy code is removed from mainline.

**Steps:**
1. Identify the exact git commit that produced the `v1.0.1` image (`docker inspect` labels / build records / commit history). If a `v1.0.1` git tag does not already exist, create an annotated tag on that commit: `git tag -a v1.0.1 -m "Final release with BreedBase legacy compatibility (format=breedbase)"` and push it.
2. Record the image digest for true immutability: `docker inspect --format='{{index .RepoDigests 0}}' hkmanchi/sorghum-breedbase-image-pipeline:v1.0.1`.
3. Publish a GitHub Release for `v1.0.1` with notes stating it is the last release carrying the legacy BreedBase response path, and that it is frozen (no further changes).
4. Document, in this tracker and in a repo deprecation note, which BreedBase instance URL(s) / `server_endpoint`(s) depend on this image, and confirm those configs pin `:v1.0.1` (not `:latest`).

**Expected outputs:** Annotated git tag `v1.0.1` matching the running image; recorded image digest; GitHub Release `v1.0.1` (frozen); documented list of dependent instances/endpoints.

---

### Subtask 2 — Adopt SemVer release process + Docker tag parity

- [x] Status: In progress — `VERSIONING.md` and `.github/workflows/release.yml` created (2026-07-10). Steps 1, 2, and 4 documented; Step 3 `:latest` consumer deprecation to be reflected in README during Subtask 8. Remaining: add `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` secrets and confirm a root `Dockerfile` before first tagged build.

**Purpose:** Make releases immutable and citable, keep git/GitHub/Docker versions in lockstep, and retire the `:latest` anti-pattern.

**Steps:**
1. Add a short `VERSIONING.md` (or a section in `CONTRIBUTING`) defining SemVer policy and the three version axes above; state that breaking contract changes bump the major version.
2. Add CI (GitHub Actions) that, on push of a `vX.Y.Z` git tag, builds and pushes the matching Docker tag `hkmanchi/sorghum-breedbase-image-pipeline:X.Y.Z` (pinned by digest in release notes).
3. Stop publishing `:latest` as the recommended tag for BreedBase; document version pinning as required for consumers.
4. Note the mapping: release version ↔ `openapi.yml info.version` ↔ envelope `schema_version` are tracked but move independently.

**Expected outputs:** `VERSIONING.md`; CI workflow tagging Docker images from git tags; documented deprecation of `:latest` for consumers.

---

### Subtask 3 — Remove `output_mode` from framework + reference pipeline

- [x] Status: Done — `output_mode` removed from `process_image.py`, `api/app.py`, `cli.py`, and `api/config/openapi.yml` on branch `feat/canonical-only-v2` (2026-07-10). Pipeline now always emits all six `TRAITS_MAP` traits. Tests/fixtures updated to match. Details: `docs/Subtask_3-5_Change_Log.md`.

**Purpose:** Collapse to one canonical output. A pipeline emits every trait it computes; "single vs all" is not a framework concern.

**Steps:**
1. `process_image.py`: remove `DEFAULT_OUTPUT_MODE` and `select_internal_trait_keys()`; emit all keys in `TRAITS_MAP`; drop the `output_mode` parameter and the `output_mode` field from the returned dict; set `traits_emitted` = all public trait keys.
2. `app.py`: remove the `output_mode = request.args.get("output_mode")` read and the argument passed to `analyze_image(...)`; remove `output_mode` from the built envelope.
3. `cli.py`: remove the `--output-mode` argument and its use; remove `output_mode` from the CLI envelope.
4. `openapi.yml`: remove the `output_mode` query parameter and the `output_mode` response property.
5. Update tests/fixtures that reference `output_mode`.

**Expected outputs:** Canonical-only pipeline that always emits all defined traits; `output_mode` removed from all four files and tests; diffs recorded for the `v2.0.0` release notes.

---

### Subtask 4 — Remove the legacy response path + move pipeline params out of the contract

- [x] Status: Done — `_to_breedbase_legacy()` and the `format`/`resp_format` branch deleted from `api/app.py`; `marker_diameter_in` no longer read from the HTTP request, now defaults from `MARKER_DIAMETER_IN` env var via `process_image.py`'s `DEFAULT_MARKER_DIAMETER_IN` (2026-07-10, branch `feat/canonical-only-v2`). CLI options for standalone pipeline use retained in `cli.py`/`process_image.py`. `openapi.yml` requestBody was already image-only; no `format`/`marker_diameter_in` parameters existed to remove. README update deferred to Subtask 8 (flagged). Details: `docs/Subtask_3-5_Change_Log.md`.

**Purpose:** The framework contract is "submit an image → receive the canonical envelope." Legacy shaping and pipeline tuning do not belong on the HTTP surface.

**Steps:**
1. `app.py`: delete `_to_breedbase_legacy()` and the `format`/`resp_format` branch; the handler returns the canonical envelope only.
2. `app.py`: remove `marker_diameter_in = request.args.get("marker_diameter_in", ...)` from the HTTP surface.
3. Move `marker_diameter_in` into the seed pipeline as an internal default/config (e.g. env var or pipeline config), keeping it as a function argument in `process_image.py`/`cli.py` for standalone use but *not* a framework HTTP parameter.
4. `openapi.yml`: request body = `image` (multipart) only; no `format`, no `marker_diameter_in`.
5. Update README to remove `format`/`marker_diameter_in`/form-field descriptions (final README pass in Subtask 8).

**Expected outputs:** `app.py` with no legacy path and no pipeline-tuning HTTP params; `marker_diameter_in` sourced from pipeline config/default; spec request body is image-only.

---

### Subtask 5 — Formalize canonical envelope: `schema_version`, JSON Schema, path reconciliation

- [x] Status: Done — `SCHEMA_VERSION = "1.0"` added in `process_image.py` and threaded through every envelope builder (`process_image.py`, `api/app.py`, `cli.py`); `conformance/envelope.schema.json` (JSON Schema draft 2020-12) added per `Conformance_Test_Kit_Plan.md`'s location convention; `openapi.yml` path renamed `/upload` → `/analyze` (operationId/handler binding unchanged, verified live) and `info.version` bumped to `2.0.0` (2026-07-10, branch `feat/canonical-only-v2`). One deliberate deviation from `Conformance_Test_Kit_Plan.md`'s stricter draft (nullable `value`/`unit` to match real pipeline output) — flagged for review. Details: `docs/Subtask_3-5_Change_Log.md`.

**Purpose:** Make the one standard explicit, runtime-assertable, and self-consistent across spec/handler/README.

**Steps:**
1. Add a top-level `schema_version` (e.g. `"1.0"`) to the envelope in `process_image.py`, `cli.py`, and `app.py`.
2. Create a standalone `envelope.schema.json` (JSON Schema 2020-12) as the conformance authority: required `job_id`, `schema_version`, `pipeline{name,version}`, `qc{analysis_pass,...}`, `traits_emitted[]`, `objects[]{object_id, traits{Name|IMGSTAT:ID → {value, unit}}}`, `derived_images[]`. (Coordinate with `Conformance_Test_Kit_Plan.md`.)
3. Rename the path `/upload` → `/analyze` in `openapi.yml`; keep the `operationId`/handler mapping stable so the Connexion resolver still binds (`api.app.upload_image_and_process`, or rename handler in step with the operationId).
4. Bump `openapi.yml` `info.version` to `2.0.0`.

**Expected outputs:** Envelope carries `schema_version`; `envelope.schema.json` committed; spec exposes `POST /analyze` at `info.version 2.0.0`; spec/handler/README agree on path.

---

### Subtask 6 — Cut the canonical-only release `v2.0.0`

- [ ] Status: Not started (blocked by 3, 4, 5)

**Purpose:** Publish the new standard as a breaking major release above the frozen legacy `v1.0.1`.

**Steps:**
1. Land Subtasks 3–5 on main; ensure tests/conformance pass (Subtask 9).
2. Tag `git tag -a v2.0.0 -m "Canonical-only standard: remove output_mode/format, /analyze, schema_version"` and push.
3. CI builds/pushes `hkmanchi/sorghum-breedbase-image-pipeline:v2.0.0`.
4. Publish GitHub Release `v2.0.0` with a breaking-change summary and a migration section (canonical envelope, `/analyze`, no `output_mode`/`format`, `marker_diameter_in` now pipeline-internal). Do **not** overwrite `v1.0.1`.

**Expected outputs:** Immutable `v2.0.0` git tag, GitHub Release, and Docker image; `v1.0.1` untouched and still serving legacy.

---

### Subtask 7 — Update the BreedBase consumer to canonical-only

- [ ] Status: Not started (target: coordinated with `v2.0.0`)

**Purpose:** One parsing path on the BreedBase side that matches the standard, so users have a clear path on both sides.

**Steps:**
1. `ImageAnalysis.pm`: replace the `exists $message_hashref->{objects}[0]{traits}` detection; parse the canonical envelope uniformly (`objects[]`, `traits{}`, `derived_images[]`, `qc`, `job_id`, `schema_version`). A single-trait result is simply `objects[]` whose objects carry one trait.
2. `ImageAnalysis.pm`: delete the legacy single-trait branch that reads `image_link`/`trait_value`/`results`/`info`; optionally assert `schema_version` and fail clearly on mismatch.
3. `image_analysis.mas`: replace save-logic branching on service display-name strings (`"Citrus Image Multi Analysis"`, etc.) with a stable service attribute from `%services` config or with `is_multi_trait` derived from the canonical data.
4. Repoint the BreedBase instances **we control** to the `v2.0.0` `/analyze` endpoint; leave uncontrolled instances on the frozen `v1.0.1` service.

**Expected outputs:** Updated `ImageAnalysis.pm` and `image_analysis.mas` reading only the canonical envelope; controlled instances migrated to `v2.0.0`.

---

### Subtask 8 — Documentation: BreedBase wiki + repo docs

- [ ] Status: Not started

**Purpose:** One output story and one migration target for operators on either legacy track.

**Steps:**
1. Rewrite the BreedBase wiki image-analysis page to walk the canonical envelope field-by-field and show the BreedBase mapping: `objects[]` → observation units, `traits{}` (`Name|IMGSTAT:ID → value/unit`) → BrAPI observations, `qc.analysis_pass` → store/don't-store gate, `derived_images[]` → stored overlay.
2. Add a short "Deprecated compatibility (`v1.0.1`)" appendix so future devs understand why the frozen service exists — kept off the main path.
3. Update `README.md`: `/analyze` path, request = image only, canonical envelope, versioning/pinning guidance, remove `output_mode`/`format`/form-field text.
4. Cross-update `Repo_Improvement_Tracker.md` and note reconciliation with `ClaudeCode_Prompt_Contract_Change_Impact_Map.md` and `Conformance_Test_Kit_Plan.md`.

**Expected outputs:** Rewritten wiki page (canonical mapping + deprecation appendix); updated README and repo trackers.

---

### Subtask 9 — Verification & conformance

- [ ] Status: Not started (gates Subtask 6)

**Purpose:** Confirm real output validates against the new schema and the consumer round-trips before release.

**Steps:**
1. Run the reference pipeline on a fixture image; validate the envelope against `envelope.schema.json`. Update the golden fixture (`tests/fixtures/expected_output.json`) to the canonical-only shape with `schema_version`.
2. Test `POST /analyze` end-to-end (`app.py`) returns a schema-valid canonical envelope; confirm failure paths (`analysis_pass:false`, empty `objects`) still validate.
3. Smoke-test the updated BreedBase consumer against a `v2.0.0` endpoint (submit → group → save observations).
4. Confirm the frozen `v1.0.1` service still serves the legacy shape unchanged to a legacy consumer.

**Expected outputs:** Passing conformance validation; updated fixtures; consumer round-trip verified against `v2.0.0`; `v1.0.1` regression-checked.

---

## Open items / decisions to confirm

- Confirm a git commit/tag matches the deployed `v1.0.1` image; if the image was built without a corresponding git tag, reconstruct/annotate it (Subtask 1).
- Confirm `v2.0.0` (vs `v1.1.0`) is the intended number for canonical-only — recommended as major because `output_mode`/`format` removal is breaking.
- Confirm envelope `schema_version` starting value (`"1.0"` proposed) and whether it uses SemVer.
- Confirm CI/registry credentials exist to automate Docker tag parity (Subtask 2).

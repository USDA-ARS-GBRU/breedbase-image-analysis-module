# Conformance Test Kit — Build Plan

**Scope:** the Tier 2 "Conformance test kit (script + test)" item from `Repo_Improvement_Tracker.md`, expanded into a buildable plan and reconciled with the two design decisions in `CONTRIBUTING_Decisions_Summary.md` and the envelope contract in `README.md`.

**What this kit is, in one sentence:** a runnable checker that takes any pipeline's JSON output and tells you — with a clear pass/fail and precise error messages — whether it satisfies the output-envelope contract that lets BreedBase store results from any pipeline without special-casing.

**Two decisions already locked (from `CONTRIBUTING_Decisions_Summary.md`):**

1. **Strict on required, lenient on extras** (Decision 1, Option A). Enforce every required field, type, and the `Name|IMGSTAT:ID` key format; allow unknown pipeline-specific fields to pass through. A `--strict` flag opts into fully-strict behavior.
2. **Standalone JSON Schema now, guarded by a sync test** (Decision 2, Option A). Author `envelope.schema.json` from the README's documented envelope, and add a test that fails if it drifts from `config/openapi.yml`. **Update:** `openapi.yml` has since been reviewed and **confirmed to express the envelope only partially** — `qc` is an opaque object (no required `analysis_pass`), the trait-key pattern is absent, `value`/`unit` are not required (`value` is `nullable`), `pipeline.name`/`version` and `traits_emitted` are not required, `bbox` is unstructured, and the spec path is `POST /upload` while the README describes `POST /analyze`. The standalone schema therefore **remains authoritative**; deriving it from `openapi.yml` (Decision 2 Option B) stays deferred until the spec is enriched to full parity.

**Three envelope-semantics decisions folded in (from the session review, items 2–4):**

- **Item 2 — `value` is required *when a trait is present*, and failure is modeled by absence, not null.** A trait object that exists must carry a real `number` value and its `unit`; a key mapped to `value: null` is not storable and is disallowed. Whole-image failure ⇒ `analysis_pass: false`, `objects: []`, `traits_emitted: []`; per-object failure ⇒ the object's `qc` flags carry the reason and the trait key is simply omitted for that object.
- **Item 3 — `qc.analysis_pass` (boolean) is required; its *criteria* are pipeline-specific and are never encoded in the schema.** `qc` stays open (`additionalProperties: true`) so pipelines add their own flags; known optional flags are typed only *when present*. `traits_emitted` and `objects` are required as arrays but may be empty (empty on failure). An optional success-implies-output conditional (`if analysis_pass == true then traits_emitted minItems 1 and objects minItems 1`) is offered as a `--strict`-tier check.
- **Item 4 — trait-key pattern enforcement placement depends on the OpenAPI version.** OpenAPI 3.0 cannot constrain map keys (`propertyNames`/`patternProperties` are outside its schema subset), so the pattern lives in the standalone JSON Schema regardless. Promoting it into `openapi.yml` requires an upgrade to OpenAPI 3.1 — **gated on the repo impact map below.**

> **⏳ Pending — gated on the repo impact map.** The choices that touch `openapi.yml` (the 3.1 upgrade, moving the trait-key pattern into the spec, the `/upload`↔`/analyze` path rename, and reconciling the `format`/`marker_diameter_in` request params) are **on hold** until the read-only investigation in `ClaudeCode_Prompt_Contract_Change_Impact_Map.md` is run against the real repo and produces `docs/contract_change_impact_map.md`. That map determines whether 3.1 forces a Connexion major-version upgrade and what would break the live BreedBase integration. Nothing in this plan that lives in `conformance/` or `tests/` is blocked by it — only the `openapi.yml` enrichment and the strength of the sync test (Artifact 5) are. Build the standalone-schema kit now; revisit the spec-side items when the map returns.

**Audience note:** this document is written to be read two ways. Reviewers can read the *Purpose*, *Approach*, and *Pros/Cons* of each artifact to sign off on the design; an implementing developer can read the *Content*, *Access points*, and the sample code blocks to build it. Both paths are complete.

---

## Contents

1. [Kit structure at a glance](#1-kit-structure-at-a-glance)
2. [Step-by-step build sequence](#2-step-by-step-build-sequence)
3. [Artifact 1 — `conformance/envelope.schema.json`](#artifact-1--conformanceenvelopeschemajson)
4. [Artifact 2 — `conformance/validate.py` + `bb-conformance` CLI](#artifact-2--conformancevalidatepy--bb-conformance-cli)
5. [Artifact 3 — `conformance/__init__.py` and `conformance/README.md`](#artifact-3--conformance__init__py-and-conformancereadmemd)
6. [Artifact 4 — `tests/test_conformance.py`](#artifact-4--teststest_conformancepy)
7. [Artifact 5 — `tests/test_schema_matches_openapi.py`](#artifact-5--teststest_schema_matches_openapipy)
8. [Artifact 6 — `pyproject.toml` additions](#artifact-6--pyprojecttoml-additions)
9. [Artifact 7 — test fixtures](#artifact-7--test-fixtures-valid--invalid-envelopes)
10. [Artifact 8 — CI wiring](#artifact-8--ci-wiring-optional-but-recommended)
11. [How the artifacts link together](#3-how-the-artifacts-link-together)
12. [Serving a breeder, a pipeline author, and a platform developer at once](#4-serving-a-breeder-a-pipeline-author-and-a-platform-developer-equally)
13. [Verification checklist](#5-verification-checklist-before-calling-it-done)

---

## 1. Kit structure at a glance

```
breedbase-image-analysis-module/
├── conformance/
│   ├── __init__.py                    # package marker; exposes validate() and __version__
│   ├── envelope.schema.json           # THE contract, as JSON Schema (Draft 2020-12)
│   ├── validate.py                    # validator core + bb-conformance CLI
│   └── README.md                      # what the kit checks and how to run it
│
├── tests/
│   ├── test_conformance.py            # runs the validator against fixtures
│   ├── test_schema_matches_openapi.py # single-source-of-truth guard vs openapi.yml
│   └── fixtures/
│       ├── expected_output.json        # EXISTING golden envelope — must pass
│       ├── valid_minimal.json          # smallest legal envelope — must pass
│       ├── valid_extra_fields.json     # legal + unknown pipeline fields — must pass (fail under --strict)
│       ├── valid_failed_analysis.json  # analysis_pass:false, empty arrays — must pass
│       ├── invalid_missing_qc.json     # missing qc.analysis_pass — must fail
│       ├── invalid_bad_traitkey.json   # trait key without |IMGSTAT:ID — must fail
│       ├── invalid_missing_unit.json   # trait value with no unit — must fail
│       ├── invalid_null_value.json     # trait value:null — must fail (model failure by omission)
│       └── invalid_passed_but_empty.json # pass:true but no output — must fail --strict conditional
│
├── config/openapi.yml                 # EXISTING contract; sync test asserts agreement
└── pyproject.toml                     # registers bb-conformance; adds jsonschema dep
```

The kit is deliberately small and self-contained. Everything lives in two directories (`conformance/` and `tests/`) plus two edits to existing files (`pyproject.toml`, and — only if drift is found — `config/openapi.yml`). It has one runtime dependency, `jsonschema`.

---

## 2. Step-by-step build sequence

Ordered so each step is testable before the next depends on it.

1. **Add the dependency and console-script registration** to `pyproject.toml` (Artifact 6). Do this first so `pip install -e .` wires up `bb-conformance` for manual testing as you go.
2. **Write `conformance/envelope.schema.json`** (Artifact 1) directly from the README's "output envelope" section. This is the anchor; everything else validates against or agrees with it.
3. **Write `conformance/validate.py`** (Artifact 2): the `validate()` function, the trait-key/unit checks JSON Schema can't fully express, and the `bb-conformance` CLI.
4. **Add `conformance/__init__.py` and `conformance/README.md`** (Artifact 3) so the package imports cleanly and has an on-ramp doc.
5. **Create the fixture set** (Artifact 7): keep the existing `expected_output.json`, add minimal-valid, extra-fields, and three targeted invalid envelopes.
6. **Write `tests/test_conformance.py`** (Artifact 4): assert valid fixtures pass and each invalid fixture fails for the expected reason.
7. **Write `tests/test_schema_matches_openapi.py`** (Artifact 5): the drift guard. Because `openapi.yml` is confirmed to define the envelope only partially, this test runs as a **subset guard** — it asserts agreement on the fields OpenAPI *does* define and `skip`/`xfail`s the rest with a clear reason, never deleting the check.
8. **Wire CI** (Artifact 8): run `pytest` and a `bb-conformance` smoke check on push.
9. **Replace the README placeholders** — the two "*(to be added)*" mentions in the Contributing and "Building a Compatible Pipeline" sections — with real usage: `pip install`, `bb-conformance your_output.json`.
10. **Verify** against the checklist in §5.

> **Not in this sequence — gated on the impact map.** Enriching `openapi.yml` (the 3.1 upgrade, trait-key pattern in the spec, `/upload`↔`/analyze` rename, request-param reconciliation) is deliberately excluded from the steps above. It waits on `docs/contract_change_impact_map.md` (see `ClaudeCode_Prompt_Contract_Change_Impact_Map.md`). Steps 1–10 build the standalone-schema kit, which does not depend on that outcome.

---

## Artifact 1 — `conformance/envelope.schema.json`

**High-level summary.** A JSON Schema (Draft 2020-12) that encodes the output envelope documented in the README as a machine-checkable contract.

**Purpose.** It is the single, readable definition of "what a valid envelope looks like." Every other artifact points back to it: the validator loads it, the tests exercise it, the sync test compares it to `openapi.yml`, and a human contributor can read it top to bottom to understand the standard.

**Content — what it must encode** (traceable to the README "output envelope" and "Field reference" tables):

- **Required top-level fields:** `pipeline` (object with required `name`, `version` strings), `qc` (object), `objects` (array), `traits_emitted` (array of strings). These four are exactly what the README's "What a pipeline must return" lists.
- **Provenance fields the module injects:** `job_id` (string), `timestamp` (ISO 8601 string), `input.image_filename` (string). Required in a full envelope; see the note below on the module-injected vs. pipeline-emitted distinction.
- **`qc` object (item 3):** `analysis_pass` (boolean, **required**) and `object_count` (integer, required per the README's minimum QC block). `color_card_present` and `size_marker_detected` are optional booleans — declared and type-checked when present, but not required, so they never block. `qc` is `additionalProperties: true` so pipelines add their own flags freely. The schema mandates that `analysis_pass` *exists and is a boolean* — it never encodes *how* a given pipeline decides it (a color-card-dependent pipeline and a marker-dependent one both conform).
- **`traits_emitted` and `objects` (items 2–3):** both are **required arrays but may be empty**. "Required" means the key is present, not non-empty — so a failed image conforms with `analysis_pass: false`, `objects: []`, `traits_emitted: []`. An **optional success-implies-output conditional** — `if qc.analysis_pass == true then traits_emitted minItems 1 and objects minItems 1` — catches "claims success but emitted nothing"; ship it as a `--strict`-tier check, not a default, given how young the standard is.
- **`objects[]` items:** each requires `object_id` (string) and `traits` (object). Optional: `source_label`, `bbox` (object of required integers `x,y,w,h`), per-object `qc`. **Per-object failure is modeled by omission (item 2):** a seed the pipeline couldn't measure carries its reason in `objects[].qc` (e.g. `contour_found: false`) and simply lacks that trait key — it is *not* represented by a null-valued trait.
- **`traits` values (item 2):** every value is an object requiring `value` (**typed `number`, not nullable**) **and** `unit` (non-empty string). A trait object that exists must carry a real measurement; `value: null` is disallowed. This corrects the `openapi.yml` default (`value: { nullable: true }`), which would let a broken measurement pass.
- **Unit semantics (item 1).** The `unit` string is the **scale component of the trait's IMGSTAT term** (each term bundles trait + method + scale), not free-form metadata. The structural schema can only check that `unit` is a non-empty string; confirming the unit *matches the scale defined by the IMGSTAT term the key names* is a deeper, ontology-aware check that needs a pinned IMGSTAT release. Note it as a **future validation layer** (see Artifact 2's roadmap note), out of scope for the first structural kit.
- **Trait-key format (item 4):** the *keys* of every `traits` object must match `^.+\|IMGSTAT:\d{7}$` (human label, a pipe, then `IMGSTAT:` and a 7-digit ID, e.g. `...|IMGSTAT:0000008`). JSON Schema expresses this with `propertyNames.pattern`. This rule lives in the standalone schema **regardless of the OpenAPI decision** — OpenAPI 3.0 cannot express it at all, and only an upgrade to 3.1 (gated on the impact map) could move it into `openapi.yml`. Confirm IMGSTAT IDs are always 7 digits; if width varies, use `\d+`. (See the caveat under Artifact 2 — `propertyNames` is the right tool but error messages are weak, so the CLI adds a friendlier check.)
- **Leniency:** top level and object level set `"additionalProperties": true` so unknown pipeline-specific fields pass. This is Decision 1 Option A in schema form. The `--strict` mode (Artifact 2) overrides these to `false` at load time.

**Access points.** Loaded by path from `validate.py` via `importlib.resources` (so it works from an installed wheel, not just a source checkout). Never imported as code — it is data.

**Links to other artifacts/inputs.** *Derived from:* the README envelope. *Consumed by:* `validate.py` (Artifact 2). *Checked against:* `config/openapi.yml` by `test_schema_matches_openapi.py` (Artifact 5). *Exercised by:* all fixtures (Artifact 7).

**Sample content** (abridged — real file spells out every trait-bearing branch):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/USDA-ARS-GBRU/breedbase-image-analysis-module/conformance/envelope.schema.json",
  "title": "BreedBase Image Analysis output envelope",
  "type": "object",
  "required": ["pipeline", "qc", "objects", "traits_emitted"],
  "additionalProperties": true,
  "properties": {
    "job_id":    { "type": "string" },
    "timestamp": { "type": "string", "format": "date-time" },
    "pipeline": {
      "type": "object",
      "required": ["name", "version"],
      "properties": {
        "name":    { "type": "string", "minLength": 1 },
        "version": { "type": "string", "minLength": 1 }
      }
    },
    "input": {
      "type": "object",
      "properties": { "image_filename": { "type": "string" } }
    },
    "qc": {
      "type": "object",
      "required": ["analysis_pass"],
      "additionalProperties": true,
      "properties": {
        "analysis_pass":       { "type": "boolean" },
        "object_count":        { "type": "integer", "minimum": 0 },
        "color_card_present":  { "type": "boolean" },
        "size_marker_detected":{ "type": "boolean" }
      }
    },
    "output_mode":    { "type": "string", "enum": ["single", "all"] },
    "traits_emitted": { "type": "array", "items": { "type": "string" } },
    "derived_images": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "role":     { "type": "string" },
          "filename": { "type": "string" },
          "url":      { "type": "string" }
        }
      }
    },
    "objects": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["object_id", "traits"],
        "additionalProperties": true,
        "properties": {
          "object_id":    { "type": "string" },
          "source_label": { "type": "string" },
          "bbox": {
            "type": "object",
            "required": ["x", "y", "w", "h"],
            "properties": {
              "x": { "type": "integer" }, "y": { "type": "integer" },
              "w": { "type": "integer" }, "h": { "type": "integer" }
            }
          },
          "qc": { "type": "object", "additionalProperties": true },
          "traits": {
            "type": "object",
            "minProperties": 1,
            "propertyNames": { "pattern": "^.+\\|IMGSTAT:\\d{7}$" },
            "additionalProperties": {
              "type": "object",
              "required": ["value", "unit"],
              "properties": {
                "value": { "type": "number" },
                "unit":  { "type": "string", "minLength": 1 }
              }
            }
          }
        }
      }
    }
  }
}
```

**Best approach + pros/cons.**

- **Chosen: hand-authored standalone JSON Schema, Draft 2020-12.**
  - *Pros:* works with no repo/OpenAPI access; JSON Schema is the natural, precise tool for validating JSON and gives field-level error paths; readable as documentation in its own right; no coupling to Connexion internals. (Mirrors Decision 2 Option A.)
  - *Cons:* a second definition of the contract now exists alongside `openapi.yml`, so it can drift — mitigated by Artifact 5's sync test. Draft 2020-12 needs a reasonably current `jsonschema` (≥ 4.18); pin it.
- **Rejected: derive the schema from `openapi.yml` at runtime.** Single source of truth, but OpenAPI response bodies often under-specify nested shapes (the per-object `traits` map especially), adding a parsing dependency for weaker validation. Revisit only if `openapi.yml` is confirmed to fully express the envelope.

**One decision to confirm during build — module-injected fields.** The README says the module injects `job_id`, `timestamp`, `input.image_filename`, and provenance automatically; a *pipeline's* raw stdout may not carry them. Recommended handling: make these required in the default schema (the envelope BreedBase receives is complete), but have the CLI accept a `--pipeline-output` mode that relaxes the four module-injected fields to optional, so an author can validate their pipeline's own output before it ever passes through the module. This keeps the standard honest without forcing authors to fake provenance.

---

## Artifact 2 — `conformance/validate.py` + `bb-conformance` CLI

**High-level summary.** The engine of the kit: a pure `validate()` function plus a thin command-line wrapper registered as `bb-conformance`.

**Purpose.** Turn the schema into an actionable answer. Pipeline authors run it to self-verify before submitting; maintainers run it (in CI or by hand) to accept pipelines without eyeballing JSON. It also catches the two things JSON Schema expresses awkwardly — the trait-key format and the presence of a unit — and reports them in plain language.

**Content — behavior.**

- `validate(envelope: dict, *, strict: bool = False, pipeline_output: bool = False) -> list[Problem]` — returns a list of structured problems (empty list = valid). Each `Problem` carries `path` (JSON pointer like `objects[3].traits`), `message`, and `severity`.
- Loads `envelope.schema.json` via `importlib.resources`, runs `jsonschema` validation, and maps each `ValidationError` to a `Problem` with a readable path.
- **Supplemental checks** beyond raw schema, for better messages: for every `objects[].traits` key, confirm it matches `Name|IMGSTAT:NNNNNNN` and say *which* key failed and why ("missing `|IMGSTAT:` segment"); for every trait value, confirm `unit` is a non-empty string.
- **`strict=True`** reloads the schema with `additionalProperties: false` injected at each level, so unknown fields (including typos like `color_card_prsent`) become failures. This is the escape hatch from Decision 1 that recovers Option B's benefit on demand.
- **`pipeline_output=True`** relaxes the four module-injected fields (see Artifact 1 note).

**Access points** (three, matching three user types):

1. **CLI:** `bb-conformance <output.json> [--strict] [--pipeline-output] [--quiet]`. Exit `0` if valid, `1` if not — so it works as a CI gate and an acceptance criterion. Prints a green "VALID" line or a numbered list of problems with JSON paths. Reads `-` for stdin so `bb-analyze ... | bb-conformance -` works.
2. **Python import:** `from conformance import validate`. Returns the problem list for programmatic use (batch-checking a directory of outputs, wiring into another test suite).
3. **Pytest:** consumed indirectly by Artifact 4.

**Links to other artifacts/inputs.** *Reads:* `envelope.schema.json` (Artifact 1) and the target output file. *Registered by:* `pyproject.toml` (Artifact 6). *Exercised by:* `test_conformance.py` (Artifact 4). *Referenced from:* the README's Contributing and "Building a Compatible Pipeline" sections and `conformance/README.md`.

**Sample content** (core skeleton):

```python
"""bb-conformance — validate a pipeline output envelope against the contract."""
from __future__ import annotations
import argparse, json, re, sys
from dataclasses import dataclass
from importlib.resources import files
import jsonschema

TRAIT_KEY = re.compile(r"^.+\|IMGSTAT:\d{7}$")

@dataclass
class Problem:
    path: str
    message: str
    severity: str = "error"
    def __str__(self) -> str:
        return f"  [{self.severity}] {self.path or '<root>'}: {self.message}"

def _load_schema(strict: bool) -> dict:
    schema = json.loads(files("conformance").joinpath("envelope.schema.json").read_text())
    if strict:
        _forbid_extras(schema)   # walk the tree, set additionalProperties=false
    return schema

def validate(envelope: dict, *, strict: bool = False,
             pipeline_output: bool = False) -> list[Problem]:
    schema = _load_schema(strict)
    if pipeline_output:
        _relax_module_fields(schema)  # job_id/timestamp/input optional
    problems: list[Problem] = []
    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(envelope), key=lambda e: e.path):
        path = ".".join(str(p) for p in err.path)
        problems.append(Problem(path, err.message))
    # Friendlier supplemental checks (better messages than raw propertyNames)
    for i, obj in enumerate(envelope.get("objects", [])):
        for key, val in (obj.get("traits") or {}).items():
            if not TRAIT_KEY.match(key):
                problems.append(Problem(
                    f"objects[{i}].traits", f"trait key {key!r} must match "
                    f"'Name|IMGSTAT:NNNNNNN'"))
            if isinstance(val, dict) and not val.get("unit"):
                problems.append(Problem(
                    f"objects[{i}].traits[{key!r}]", "trait value is missing a unit"))
    return problems

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bb-conformance",
        description="Validate a pipeline output envelope against the BreedBase contract.")
    ap.add_argument("output", help="path to the JSON envelope, or '-' for stdin")
    ap.add_argument("--strict", action="store_true", help="reject unknown fields too")
    ap.add_argument("--pipeline-output", action="store_true",
                    help="allow missing module-injected fields (job_id, timestamp, input)")
    ap.add_argument("--quiet", action="store_true", help="print nothing; use exit code only")
    args = ap.parse_args(argv)
    raw = sys.stdin.read() if args.output == "-" else open(args.output).read()
    envelope = json.loads(raw)
    problems = validate(envelope, strict=args.strict, pipeline_output=args.pipeline_output)
    if not problems:
        if not args.quiet: print("VALID — envelope conforms to the contract.")
        return 0
    if not args.quiet:
        print(f"INVALID — {len(problems)} problem(s):")
        for p in problems: print(p)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
```

**Best approach + pros/cons.**

- **Chosen: `jsonschema` for structure + a thin supplemental layer for the two awkward checks.**
  - *Pros:* leans on a mature library for the hard part (nested structure, types, paths); the supplemental layer exists only where JSON Schema's messages are unhelpful (`propertyNames` reports "does not match" without naming the offending key). Small, dependency-light, easy to read.
  - *Cons:* two places now encode the trait-key rule (the schema pattern and the regex in code). Keep them identical; the fixture `invalid_bad_traitkey.json` will catch divergence.
- **Rejected: pure hand-rolled validation (no `jsonschema`).** No dependency, but you re-implement path tracking, type coercion, and array handling — more code, more bugs, worse messages.
- **Rejected: `pydantic` models.** Great ergonomics, but it pulls a heavier dependency and models are less self-evidently "the contract" than a JSON Schema a reviewer can read.

**Roadmap note — ontology-aware unit check (item 1).** The structural kit verifies that a trait key is well-formed and that its value carries a non-empty `unit`. It does **not** yet verify that the `unit` matches the *scale* the named IMGSTAT term defines (each term = trait + method + scale). That check requires resolving the key's `IMGSTAT:ID` against a **pinned IMGSTAT release** and comparing scales — a natural second validation layer (`--imgstat <release>` mode) once the ontology repo exposes a lookup. Design `validate()` so a future term-resolver plugs in as an additional problem source, not a rewrite. Out of scope for the first build; flagged so the structural pass isn't mistaken for full ontological conformance.

---

## Artifact 3 — `conformance/__init__.py` and `conformance/README.md`

**High-level summary.** The package marker that makes `conformance/` importable and ships the schema as package data, plus a short human-facing doc.

**Purpose.** `__init__.py` re-exports `validate` and a `__version__` so `from conformance import validate` works and so the schema is discoverable via `importlib.resources`. `README.md` is the on-ramp: what the kit checks, how to install and run it, how to read the output, and the strict-vs-lenient distinction — one screen, no prior context assumed.

**Content.** `__init__.py`: `from .validate import validate, main, Problem` and `__version__`. `README.md`: a 5-line "what this is," an install line (`pip install -e .`), the three access points with one example each, a table of the exit codes, and a short "what counts as valid" summary that links to `envelope.schema.json` as the authority.

**Access points.** `__init__.py` is imported implicitly. `README.md` is linked from the repo README's Contributing section and from the `conformance/` directory listing on GitHub.

**Links.** *Re-exports:* `validate.py`. *Documents:* Artifacts 1 and 2. *Links out to:* the repo README and `docs/PIPELINE_REQUIREMENTS.md`.

**Best approach + pros/cons.** Ship the schema as package data (declared in `pyproject.toml`) rather than reading it by relative filesystem path. *Pro:* works from an installed wheel and from CI, not just a source tree. *Con:* one extra line of packaging config — trivial.

---

## Artifact 4 — `tests/test_conformance.py`

**High-level summary.** The automated test that proves the validator accepts good envelopes and rejects bad ones for the right reasons.

**Purpose.** Regression protection for the kit itself. It guarantees the existing golden output (`tests/fixtures/expected_output.json`) stays conformant, and that each failure mode the standard cares about is actually caught — so a future refactor of `validate.py` can't silently weaken the gate.

**Content.**

- **Valid cases:** `expected_output.json`, `valid_minimal.json`, and `valid_extra_fields.json` each produce **zero** problems in default mode. `valid_extra_fields.json` produces problems in `--strict` mode (proving strict actually tightens).
- **Invalid cases:** parametrized — each invalid fixture yields ≥1 problem, and the assertion checks the problem's `path`/`message` matches the intended defect (missing `qc.analysis_pass`, malformed trait key, missing unit). Testing *why* it failed, not just *that* it failed, prevents a fixture from passing for an accidental reason.
- **`--pipeline-output` case:** an envelope lacking `job_id`/`timestamp` passes under `pipeline_output=True` and fails without it.

**Access points.** `pytest` (locally and in CI). Reads fixtures from `tests/fixtures/`.

**Links.** *Calls:* `conformance.validate` (Artifact 2). *Reads:* fixtures (Artifact 7). *Runs under:* CI (Artifact 8).

**Sample content:**

```python
import json, pathlib, pytest
from conformance import validate

FIX = pathlib.Path(__file__).parent / "fixtures"
def load(name): return json.loads((FIX / name).read_text())

@pytest.mark.parametrize("name", ["expected_output.json", "valid_minimal.json",
                                   "valid_extra_fields.json"])
def test_valid_envelopes_pass(name):
    assert validate(load(name)) == []

def test_extra_fields_fail_under_strict():
    assert validate(load("valid_extra_fields.json"), strict=True)  # non-empty

@pytest.mark.parametrize("name,needle", [
    ("invalid_missing_qc.json",     "analysis_pass"),
    ("invalid_bad_traitkey.json",   "IMGSTAT"),
    ("invalid_missing_unit.json",   "unit"),
])
def test_invalid_envelopes_fail_for_the_right_reason(name, needle):
    problems = validate(load(name))
    assert any(needle in (p.message + p.path) for p in problems), \
        f"{name} should have failed on {needle}; got {[str(p) for p in problems]}"
```

**Best approach + pros/cons.** Fixture-driven, parametrized. *Pros:* adding a new failure mode is one fixture + one row; reads as a spec of what the standard rejects. *Cons:* fixtures live apart from the assertions, so a reader hops files — mitigated by descriptive fixture names.

---

## Artifact 5 — `tests/test_schema_matches_openapi.py`

**High-level summary.** The single-source-of-truth guard: a test that fails if `envelope.schema.json` and `config/openapi.yml` describe different envelopes.

**Purpose.** Decision 2 accepts a standalone schema on the condition that drift is caught mechanically. This test is that condition. Without it, the two contract definitions silently diverge and "conformance" starts meaning two different things.

**Content.** Load both, extract the envelope response schema from `openapi.yml`, and assert agreement on the parts OpenAPI actually specifies: required top-level keys and types. Compare *sets of required fields* and *types*, not byte-for-byte JSON.

**Handling the confirmed-partial spec.** `openapi.yml` has now been reviewed and **only partially expresses the envelope** (see the preamble), so this is a **subset guard, not a full-agreement assertion** — and cannot become one until the spec is enriched (gated on the impact map). Two spec facts change how the test is written:

- **Path.** The spec defines the operation at `POST /upload` (operationId `api.app.upload_image_and_process`), *not* `POST /analyze`. The walker must try `/upload` (and tolerate `/analyze` if the path is later reconciled) rather than hard-coding one — otherwise the test silently finds nothing and skips.
- **Coverage.** `openapi.yml` today does not require `traits_emitted`, leaves `qc` opaque (no `analysis_pass`), does not require `pipeline.name`/`version`, and does not express the trait-key pattern or `value`/`unit` requirements. So the test can only assert the subset it *does* define (currently: presence of `job_id`, `pipeline`, `qc`, `objects` in `required`, and `object_id`/`traits` on object items).

Build it defensively:

- If `openapi.yml` is missing or the walker finds no envelope body, `pytest.skip("openapi.yml does not specify the /upload envelope body; standalone schema is authoritative — see Decision 2")` — a visible reminder, not a silent gap.
- Assert only on the fields the spec defines (`required`-set is a *subset* of the standalone schema's `required`), and `xfail` the known-missing pieces with reasons that name the enrichment gap. As `openapi.yml` is enriched (post-impact-map), promote each `xfail` to a hard assertion; once the spec fully expresses the envelope, this test flips to full agreement and Decision 2 Option B (derive-from-spec) becomes viable.

**Access points.** `pytest` / CI.

**Links.** *Reads:* `envelope.schema.json` (Artifact 1) and `config/openapi.yml` (existing). Realizes the safety net Decision 2 depends on.

**Sample content** (defensive shape):

```python
import json, pathlib, pytest
yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "conformance" / "envelope.schema.json"
OPENAPI = ROOT / "config" / "openapi.yml"

# Try the current spec path (/upload) first, tolerate a future /analyze rename.
CANDIDATE_PATHS = ("/upload", "/analyze")

def _envelope_from_openapi(spec):
    for path in CANDIDATE_PATHS:
        try:
            return spec["paths"][path]["post"]["responses"]["200"] \
                       ["content"]["application/json"]["schema"]
        except KeyError:
            continue
    return None

def test_schema_is_superset_of_openapi():
    """Subset guard: everything openapi.yml requires must also be required by the
    standalone schema. openapi.yml is confirmed partial, so this is one-directional
    until the spec is enriched (gated on the impact map)."""
    if not OPENAPI.exists():
        pytest.skip("openapi.yml not present; standalone schema is authoritative (Decision 2)")
    spec = yaml.safe_load(OPENAPI.read_text())
    oapi = _envelope_from_openapi(spec)
    if not oapi or "properties" not in oapi:
        pytest.skip("openapi.yml does not specify the /upload envelope body; "
                    "standalone schema authoritative (Decision 2)")
    schema = json.loads(SCHEMA.read_text())
    assert set(oapi.get("required", [])) <= set(schema["required"]), \
        "openapi.yml requires top-level fields the JSON Schema does not"

@pytest.mark.xfail(reason="openapi.yml is confirmed partial; enrich post-impact-map, "
                          "then promote to a hard assertion (Decision 2 Option B path)")
def test_openapi_fully_expresses_envelope():
    """Aspirational: once openapi.yml expresses qc.analysis_pass, the trait-key
    pattern, value/unit requirements, and pipeline requireds, the two required-sets
    should match exactly. Flip this from xfail to a real assertion when that lands."""
    spec = yaml.safe_load(OPENAPI.read_text())
    oapi = _envelope_from_openapi(spec)
    schema = json.loads(SCHEMA.read_text())
    assert set(oapi["required"]) == set(schema["required"])
```

**Best approach + pros/cons.** Compare semantically (required-sets and types), as a one-directional subset guard while the spec is partial, with an `xfail` placeholder for the eventual full-agreement assertion. *Pros:* honors Decision 2 exactly; never blocks on the known OpenAPI gaps but keeps them visible in the test report; the `xfail` is a standing to-do that turns green (and gets promoted) the moment the spec is enriched. *Cons:* a skipped/xfailed test can be ignored — counter it by surfacing skip/xfail reasons in the CI summary and listing the open enrichment item in `conformance/README.md` and the impact map.

---

## Artifact 6 — `pyproject.toml` additions

**High-level summary.** Two small edits: add `jsonschema` as a dependency and register the `bb-conformance` console script; declare the schema as package data.

**Purpose.** Makes the CLI real (`pip install` → `bb-conformance` on `PATH`) and ensures the schema ships with the package.

**Content.**

```toml
[project]
dependencies = [
  # ...existing...
  "jsonschema>=4.18",         # Draft 2020-12 support
]

[project.scripts]
bb-conformance = "conformance.validate:main"

[tool.setuptools.package-data]
conformance = ["envelope.schema.json"]
```

Match the existing build backend — if the repo already uses `pyproject.toml` to register `bb-analyze` (it does, per the README), mirror that block exactly for consistency.

**Access points.** Consumed by `pip`/the build backend at install time. After install, `bb-conformance` is the CLI entry point from Artifact 2.

**Links.** *Registers:* `validate.py:main` (Artifact 2). *Packages:* `envelope.schema.json` (Artifact 1). Parallels the existing `bb-analyze` registration.

**Best approach + pros/cons.** Add the console script and dependency to the existing project metadata (no separate package). *Pros:* one install gives users both `bb-analyze` and `bb-conformance`; nothing new to publish. *Cons:* couples the checker's release to the main package — acceptable while they evolve together; split into its own distributable only if other repos want the checker without the pipeline.

---

## Artifact 7 — test fixtures (valid + invalid envelopes)

**High-level summary.** A small library of example envelopes — some legal, some deliberately broken — that both the tests and curious humans learn the contract from.

**Purpose.** Give the tests concrete inputs and give pipeline authors copy-paste examples of exactly what passes and what fails. The invalid fixtures double as documentation of the standard's teeth.

**Content.**

- **`expected_output.json`** — already exists; the golden full envelope. The kit must not require changes to it (if it does, the schema is wrong, not the fixture).
- **`valid_minimal.json`** — the smallest thing that passes: one pipeline block, `qc.analysis_pass`, one object with one correctly-keyed trait carrying value + unit, a matching `traits_emitted`. Shows the floor.
- **`valid_extra_fields.json`** — valid plus unknown fields (`qc.color_card_prsent` typo lives here intentionally, plus a bespoke `objects[].traits[...].confidence`). Passes by default, fails under `--strict` — the fixture that proves Decision 1 works both ways.
- **`invalid_missing_qc.json`** — omits `qc.analysis_pass`.
- **`invalid_bad_traitkey.json`** — a trait keyed `Object Max Diameter` with no `|IMGSTAT:ID`.
- **`invalid_missing_unit.json`** — a trait value `{ "value": 4.3 }` with no `unit`.
- **`invalid_null_value.json`** (item 2) — a trait value `{ "value": null, "unit": "mm" }`. Must fail: failure is modeled by *omitting* the trait, never by a null value.
- **`valid_failed_analysis.json`** (items 2–3) — a whole-image failure: `qc.analysis_pass: false`, `objects: []`, `traits_emitted: []`. Must **pass** the default schema (empty arrays are legal) and, if the optional success-implies-output conditional is enabled, must still pass because `analysis_pass` is false. Documents the sanctioned "nothing measured" envelope.
- **`invalid_passed_but_empty.json`** (item 3, `--strict`-tier only) — `qc.analysis_pass: true` with `traits_emitted: []` / `objects: []`. Passes the default schema but must **fail** the success-implies-output conditional, proving that check works.

**Access points.** Read by `test_conformance.py`; linkable on GitHub as worked examples from `conformance/README.md`.

**Links.** *Derived from:* the README envelope. *Consumed by:* Artifact 4. *Illustrate:* Artifact 1's rules.

**Best approach + pros/cons.** One fixture per failure mode, minimal and single-purpose. *Pros:* a failing test points at exactly one defect; fixtures read as a catalog of "don't do this." *Cons:* several tiny files — offset by the naming convention (`valid_*` / `invalid_*`).

---

## Artifact 8 — CI wiring (optional but recommended)

**High-level summary.** A GitHub Actions workflow that installs the package and runs `pytest` plus a `bb-conformance` smoke check on every push and PR.

**Purpose.** Makes conformance continuous, not a one-time manual step, and makes the kit's own tests part of the merge gate. It also demonstrates to pipeline authors the exact command they can copy into their own CI.

**Content.** A workflow that runs `pip install -e ".[api]"`, `pytest tests/`, and `bb-conformance tests/fixtures/expected_output.json`. On a matrix of Python 3.9–3.12 to match the README's "Python 3.9+" claim.

**Access points.** Runs on `push`/`pull_request`; surfaces as a status check on PRs.

**Links.** *Runs:* Artifacts 4 and 5 (via pytest) and Artifact 2 (via the CLI smoke check). *Referenced by:* the "Propose a pipeline" issue template (a separate Tier 2 item) as the check authors must pass.

**Best approach + pros/cons.** GitHub Actions, matrixed on supported Python versions. *Pros:* zero-infra, native to the repo, doubles as a copyable example for authors. *Cons:* adds a maintenance surface (action version bumps) — minimal, and worth it for a standard that lives or dies on trust.

---

## 3. How the artifacts link together

The dependency flow, from contract to gate:

```
README "output envelope"  ─┐
                           ├─►  envelope.schema.json  (Artifact 1, the anchor)
config/openapi.yml  ───────┘         │
        ▲                            ├─► validate.py / bb-conformance (Artifact 2)
        │                            │         │
        │  test_schema_matches_      │         ├─► pyproject.toml registers CLI (Artifact 6)
        └──openapi.py (Artifact 5) ◄─┘         │
                                     │         ▼
   fixtures (Artifact 7) ───────────►└──► test_conformance.py (Artifact 4)
                                                │
                                                ▼
                                          CI (Artifact 8)  ──► status check on PRs
```

Reading it in words: the README envelope is the source; `envelope.schema.json` encodes it; `validate.py` enforces it and is exposed three ways (CLI, import, tests); `pyproject.toml` publishes the CLI; the fixtures and `test_conformance.py` prove the enforcement is correct; `test_schema_matches_openapi.py` keeps the schema honest against `openapi.yml`; CI runs the lot on every change. The two README "*(to be added)*" placeholders resolve to "run `bb-conformance your_output.json`."

---

## 4. Serving a breeder, a pipeline author, and a platform developer equally

The design challenge the kit has to solve is that one artifact set must speak to three very different readers **without softening the precision the standard depends on.** The move is not to write three different things — it is to layer one precise artifact so each reader enters at the altitude they need and can descend to the exact rule when they want it. Precision lives in one place (`envelope.schema.json`); everything else is a labelled door into it.

**The breeder / researcher** rarely runs the checker directly — they produce images and read results. What they need from the kit is *confidence that a QC failure means something.* Serve them through the `conformance/README.md` "what counts as valid" summary written in the README's own plain-language register ("every measurement carries a unit; every result says whether calibration succeeded"), and through the `bb-conformance` output being human-readable ("trait value is missing a unit" — not a stack trace). They never see JSON Schema, but the guarantee it enforces is stated in words they already know from the repo's glossary and Troubleshooting table. Nothing is dumbed down; the same rule is simply *named* before it is *specified*.

**The pipeline author** is the primary user and needs the full precision, fast. Serve them with the three access points in ascending commitment: run `bb-conformance my_output.json` to get a verdict in seconds; read `valid_minimal.json` and `valid_extra_fields.json` to see the floor and the freedom (Decision 1's "innovate in extra fields"); read `envelope.schema.json` when they want the letter of the law. The `--pipeline-output` mode meets them where they actually are — validating raw pipeline stdout before the module adds provenance — so the standard doesn't force them to fake fields. The invalid fixtures tell them, by example, exactly what will bounce.

**The platform / BreedBase developer** needs to trust the gate and integrate it. Serve them with `validate()` as an importable function (no shelling out), exit codes suitable for a gate, the `--strict` mode for a tighter internal bar, and `test_schema_matches_openapi.py` as evidence that the checker agrees with the OpenAPI contract their integration is built on. They read the schema as the interface spec and the sync test as its guarantee of staying in step with `openapi.yml`.

**How precision survives all three.** There is exactly one normative artifact — `envelope.schema.json` — and one enforcement path — `validate.py`. The README summary, the fixtures, and the CLI messages are *views* onto that single source, never independent restatements that could drift. A breeder's plain-language sentence, an author's example fixture, and a developer's schema clause all resolve to the same rule object. That is what lets the kit be approachable at the top and exact at the bottom without the two versions ever disagreeing: they are the same thing, described at different depths.

---

## 5. Verification checklist (before calling it done)

- [ ] `pip install -e ".[api]"` succeeds and `bb-conformance --help` prints.
- [ ] `bb-conformance tests/fixtures/expected_output.json` exits `0` and prints "VALID".
- [ ] Each `invalid_*.json` exits `1` and names the intended defect.
- [ ] `valid_extra_fields.json` passes by default, fails under `--strict`.
- [ ] `valid_failed_analysis.json` (analysis_pass:false, empty arrays) passes; `invalid_null_value.json` fails (item 2 — failure by omission, not null).
- [ ] `invalid_passed_but_empty.json` passes the default schema but fails the `--strict` success-implies-output conditional (item 3).
- [ ] `bb-analyze sample.jpg --output-dir out && bb-conformance out/image_metadata_*.json` passes end to end (the checker accepts the reference pipeline's real output — the ultimate self-consistency test).
- [ ] `pytest tests/` is green; the subset guard asserts on what `openapi.yml` defines (walking `/upload`) and `skip`/`xfail`s the rest with reasons naming the enrichment gap (item 4).
- [ ] The two README "*(to be added)*" conformance mentions are replaced with real install + run instructions.
- [ ] `conformance/README.md` states the valid/invalid contract in plain language and links `envelope.schema.json` as the authority.

**Blocked pending `docs/contract_change_impact_map.md` (do not attempt until the map returns):**

- [ ] Decide 3.1 upgrade vs. keep spec at 3.0 with the trait-key pattern in the standalone schema only (item 4).
- [ ] If enriching `openapi.yml`: add required `qc.analysis_pass`, trait-key pattern, required `value`/`unit`, `pipeline` requireds, `bbox` shape; reconcile `/upload`↔`/analyze` and the `format`/`marker_diameter_in` request params — then promote `test_openapi_fully_expresses_envelope` from `xfail` to a real assertion.

---

*Sources: `Repo_Improvement_Tracker.md` (Tier 2 — Conformance test kit), `CONTRIBUTING_Decisions_Summary.md` (Decisions 1 and 2), `README.md` (output envelope, field reference, BrAPI/IMGSTAT trait-key rules), the reviewed `openapi.yml` (confirmed partial), and the session decisions on items 1–4. Spec-side enrichment is gated on `ClaudeCode_Prompt_Contract_Change_Impact_Map.md` → `docs/contract_change_impact_map.md`. All files in this project folder.*

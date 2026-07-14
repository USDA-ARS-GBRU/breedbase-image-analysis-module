"""
bb-conformance — validate a pipeline output envelope against the BreedBase contract.
================================================================================

WHAT THIS FILE IS
-----------------
The engine of the conformance kit (Conformance_Test_Kit_Plan.md, Artifact 2). It
turns the canonical output envelope — defined once, as data, in
`conformance/envelope.schema.json` (Artifact 1) — into an actionable pass/fail with
precise, human-readable error messages. Three audiences use it, three ways:

    1. CLI       :  bb-conformance my_output.json [--strict] [--pipeline-output] [--quiet]
    2. Python    :  from conformance import validate ; problems = validate(envelope)
    3. Pytest    :  driven indirectly by tests/test_conformance.py (Artifact 4)

HOW IT WORKS (high level)
-------------------------
    envelope (dict)
        │
        ├─►  jsonschema Draft 2020-12  ── structural validation against the schema
        │        │                         (types, required keys, nullable value/unit,
        │        │                          bbox null-or-{x,y,w,h}, schema_version const)
        │        └─► mapped to Problem(path, message) with a readable JSON path
        │
        ├─►  supplemental trait-key check  ── friendlier message than raw propertyNames,
        │                                      naming the offending key (see DESIGN NOTE 1)
        │
        └─►  strict-tier conditional (only with --strict)
                                          ── "success implies output": analysis_pass==true
                                             must come with non-empty objects + traits_emitted

    returns  list[Problem]   (empty list == VALID)

DESIGN DECISIONS BAKED IN (approved 2026-07-14 — see the plan's Revision Log)
-----------------------------------------------------------------------------
  A. --pipeline-output relaxes ONLY the module-injected fields `job_id` and
     `derived_images` (timestamp/input are already optional in the schema;
     schema_version + pipeline stay required — they are pipeline-emitted, not
     run-context provenance). See `_relax_module_fields`.
  B. The strict success-implies-output conditional lives here (not in the schema),
     shipped as a --strict-tier check. See `_strict_conditional_problems`.
  C. A malformed trait key is reported ONCE: the schema's `propertyNames` error is
     suppressed in favor of the friendlier supplemental message. See `_schema_problems`.

WHERE FUTURE IMPROVEMENTS SIT (search for "IMPROVEMENT:")
--------------------------------------------------------
  * IMPROVEMENT (ontology): an `--imgstat <release>` mode that resolves each trait
    key's IMGSTAT:ID against a pinned ontology release and confirms the `unit`
    matches the term's scale. validate() is built so a term-resolver plugs in as an
    ADDITIONAL problem source (one more `_..._problems()` call), not a rewrite.
  * IMPROVEMENT (messages): value/unit key-presence is currently owned by the schema
    ('required' errors). If a friendlier message is wanted, move it into the
    supplemental layer and suppress the schema 'required' error the same way keys are.
  * IMPROVEMENT (severity): every Problem is currently severity="error". A warning
    tier (e.g. deprecations) can be added without changing callers.
================================================================================
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import jsonschema

# ---------------------------------------------------------------------------
# Trait-key format. This is the SAME rule as the schema's
# `traits.propertyNames.pattern`, duplicated here only so we can emit a message
# that names the offending key. The two MUST stay identical; the
# `invalid_bad_traitkey.json` fixture (Artifact 7) fails if they diverge.
# Format: "<human label>|IMGSTAT:<7 digits>"  e.g. "Object Solidity|IMGSTAT:0000011"
# ---------------------------------------------------------------------------
TRAIT_KEY = re.compile(r"^.+\|IMGSTAT:\d{7}$")

# Module-injected ("provenance") fields that a raw pipeline's own stdout would not
# carry — relaxed by --pipeline-output (Decision A). Only these two are *required*
# by the schema; `timestamp`/`input` are already optional, so they need no relaxing.
MODULE_INJECTED_REQUIRED = ("job_id", "derived_images")


@dataclass
class Problem:
    """One conformance defect. An empty list of these == a valid envelope.

    path     : where in the envelope, as a readable JSON path (e.g. "objects[3].traits").
    message  : plain-language description a pipeline author can act on.
    severity : "error" today; reserved for a future "warning" tier (see IMPROVEMENT).
    """
    path: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        # Rendered by the CLI, one problem per line. "<root>" when the defect is
        # at the top level (empty path).
        return f"  [{self.severity}] {self.path or '<root>'}: {self.message}"


# ===========================================================================
# SCHEMA LOADING  (data in -> jsonschema-ready dict, optionally transformed)
# ===========================================================================
def _schema_path() -> Path | None:
    """Locate envelope.schema.json.

    Primary path is `importlib.resources` so the schema ships and loads from an
    installed wheel (requires conformance/__init__.py — Artifact 3). The filesystem
    fallbacks let this run from a plain source checkout or from this review copy in
    main_repo/ before the package is installed.
    """
    # 1) Installed package data (the production path).
    try:
        p = files("conformance").joinpath("envelope.schema.json")
        if p.is_file():
            return Path(str(p))
    except (ModuleNotFoundError, FileNotFoundError):
        pass
    # 2) Source-tree / review-copy fallbacks, relative to THIS file.
    here = Path(__file__).resolve().parent
    for candidate in (
        here / "envelope.schema.json",                 # staged side-by-side (main_repo/)
        here / "conformance" / "envelope.schema.json",  # repo root layout
        here.parent / "conformance" / "envelope.schema.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def _load_schema(strict: bool) -> dict:
    """Read the schema and, if `strict`, tighten it to reject unknown fields."""
    path = _schema_path()
    if path is None:
        # Fail loudly rather than silently validating against nothing.
        raise FileNotFoundError(
            "envelope.schema.json not found (looked in the 'conformance' package "
            "and alongside this file)."
        )
    schema = json.loads(path.read_text())
    if strict:
        _forbid_extras(schema)  # Decision 1's escape hatch — see below.
    return schema


def _forbid_extras(node) -> None:
    """Recursively flip `additionalProperties` to false on every OBJECT that defines
    named `properties` — the --strict behavior that turns unknown/typo fields (e.g.
    `color_card_prsent`) into failures.

    SUBTLE / IMPORTANT: we must NOT touch nodes whose `additionalProperties` is a
    *schema* (a dict), because that is how the `traits` map types each value
    ({value, unit}). Overwriting it with `false` would reject ALL traits. So we only
    set false where there are declared `properties` AND additionalProperties is
    absent or a boolean. Walk everything else so nested objects are covered too.
    """
    if isinstance(node, dict):
        has_named_props = isinstance(node.get("properties"), dict)
        ap = node.get("additionalProperties")
        if has_named_props and not isinstance(ap, dict):
            node["additionalProperties"] = False
        # Recurse into every child schema so we reach pipeline/qc/objects.items/bbox/etc.
        for value in node.values():
            _forbid_extras(value)
    elif isinstance(node, list):
        for item in node:
            _forbid_extras(item)


def _relax_module_fields(schema: dict) -> None:
    """--pipeline-output (Decision A): drop the module-injected required fields so an
    author can validate raw pipeline stdout BEFORE the module adds provenance.
    Only `job_id` and `derived_images` are removed from the top-level `required`;
    everything else (schema_version, pipeline, qc, traits_emitted, objects) still holds.
    """
    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [k for k in required if k not in MODULE_INJECTED_REQUIRED]


# ===========================================================================
# PROBLEM SOURCES  (each returns a list[Problem]; validate() concatenates them)
# ===========================================================================
def _format_path(path_parts) -> str:
    """Render a jsonschema error path (a deque of str keys / int indices) as
    "objects[3].traits" — arrays get [i], object keys get .key.
    """
    out = ""
    for part in path_parts:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out


def _schema_problems(envelope: dict, schema: dict) -> list[Problem]:
    """Structural validation via jsonschema, mapped to friendly Problems.

    Decision C: we SUPPRESS `propertyNames` errors here because the supplemental
    layer (`_traitkey_problems`) reports the same defect with a message that names
    the offending key. Every other schema error is mapped through.
    """
    validator = jsonschema.Draft202012Validator(schema)
    problems: list[Problem] = []
    for err in sorted(validator.iter_errors(envelope), key=lambda e: list(e.path)):
        # Decision C: a bad trait key trips the schema's `traits.propertyNames`
        # constraint, but jsonschema surfaces it with the INNER keyword ("pattern")
        # as err.validator — so we detect it by schema path, not by err.validator,
        # and drop it in favor of _traitkey_problems' friendlier, key-naming message.
        if "propertyNames" in err.absolute_schema_path:
            continue
        problems.append(Problem(_format_path(err.path), err.message))
    return problems


def _traitkey_problems(envelope: dict) -> list[Problem]:
    """Supplemental trait-key check (Decision C owner): name the offending key and
    say why. Friendlier than jsonschema's raw "does not match pattern" on propertyNames.
    """
    problems: list[Problem] = []
    for i, obj in enumerate(envelope.get("objects", []) or []):
        traits = obj.get("traits") if isinstance(obj, dict) else None
        for key in (traits or {}):
            if not TRAIT_KEY.match(key):
                problems.append(Problem(
                    f"objects[{i}].traits",
                    f"trait key {key!r} must match 'Name|IMGSTAT:NNNNNNN' "
                    f"(a human label, a pipe, then 'IMGSTAT:' and a 7-digit id)",
                ))
    return problems
    # IMPROVEMENT (ontology): once a pinned IMGSTAT release is available, add a
    # sibling `_imgstat_problems(envelope, release)` that resolves each key's id and
    # checks the unit against the term's scale, then call it from validate().


def _strict_conditional_problems(envelope: dict) -> list[Problem]:
    """--strict-tier "success implies output" (Decision B): if the pipeline claims
    the image passed, it must have produced something. Kept out of the schema on
    purpose (young standard) and only enforced under --strict.
    """
    problems: list[Problem] = []
    qc = envelope.get("qc")
    passed = isinstance(qc, dict) and qc.get("analysis_pass") is True
    if passed:
        if not envelope.get("objects"):
            problems.append(Problem(
                "objects",
                "qc.analysis_pass is true but 'objects' is empty "
                "(success must imply at least one measured object)",
            ))
        if not envelope.get("traits_emitted"):
            problems.append(Problem(
                "traits_emitted",
                "qc.analysis_pass is true but 'traits_emitted' is empty "
                "(success must imply at least one emitted trait)",
            ))
    return problems


# ===========================================================================
# PUBLIC API
# ===========================================================================
def validate(envelope: dict, *, strict: bool = False,
             pipeline_output: bool = False) -> list[Problem]:
    """Validate an envelope against the canonical contract.

    Returns a list of Problems; an EMPTY list means the envelope conforms.

    strict          : also reject unknown fields (additionalProperties:false) AND
                      apply the success-implies-output conditional.
    pipeline_output : allow the module-injected fields (job_id, derived_images) to be
                      absent, for validating raw pipeline stdout pre-module.
    """
    schema = _load_schema(strict)
    if pipeline_output:
        _relax_module_fields(schema)

    # Concatenate independent problem sources. Adding a future source (e.g. the
    # ontology unit check) is one more append here — not a rewrite. (IMPROVEMENT)
    problems: list[Problem] = []
    problems += _schema_problems(envelope, schema)
    problems += _traitkey_problems(envelope)
    if strict:
        problems += _strict_conditional_problems(envelope)
    return problems


# ===========================================================================
# CLI  (bb-conformance)
# ===========================================================================
def main(argv: list[str] | None = None) -> int:
    """Console entry point. Exit 0 == valid, 1 == invalid, 2 == usage/IO error.
    Registered as `bb-conformance` in pyproject.toml (Artifact 6).
    """
    ap = argparse.ArgumentParser(
        prog="bb-conformance",
        description="Validate a pipeline output envelope against the BreedBase contract.",
    )
    ap.add_argument("output", help="path to the JSON envelope, or '-' for stdin")
    ap.add_argument("--strict", action="store_true",
                    help="also reject unknown fields and enforce success-implies-output")
    ap.add_argument("--pipeline-output", action="store_true",
                    help="allow missing module-injected fields (job_id, derived_images)")
    ap.add_argument("--quiet", action="store_true",
                    help="print nothing; communicate via exit code only")
    args = ap.parse_args(argv)

    # Read the envelope (file or stdin). IO/parse errors exit 2 — distinct from a
    # well-formed-but-invalid envelope (exit 1) so CI can tell them apart.
    try:
        raw = sys.stdin.read() if args.output == "-" else Path(args.output).read_text()
    except OSError as exc:
        if not args.quiet:
            print(f"ERROR — could not read {args.output!r}: {exc}", file=sys.stderr)
        return 2
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        if not args.quiet:
            print(f"ERROR — {args.output!r} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    problems = validate(envelope, strict=args.strict,
                        pipeline_output=args.pipeline_output)

    if not problems:
        if not args.quiet:
            print("VALID — envelope conforms to the contract.")
        return 0
    if not args.quiet:
        print(f"INVALID — {len(problems)} problem(s):")
        for p in problems:
            print(p)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

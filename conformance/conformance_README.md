# Conformance kit

A checker that takes any pipeline's JSON output and tells you — with a clear
pass/fail and precise messages — whether it satisfies the **canonical output
envelope**, the contract that lets BreedBase store results from any pipeline without
special-casing. It is **strict on required structure** (types, required keys, the
trait-key format) and **lenient on extras** (unknown pipeline-specific fields pass),
with a `--strict` mode to turn that leniency off.

`envelope.schema.json` in this directory is the normative contract; everything here
just enforces and explains it.

## Install

```bash
pip install -e ".[conformance]"
```

This pulls the one dependency (`jsonschema`) and registers the `bb-conformance`
command. (Use `.[dev]` instead if you also want the test toolchain.)

## Use it — three ways

**1. Command line**

```bash
bb-conformance path/to/output.json          # validate a file
bb-analyze sample.jpg --output-dir out && bb-conformance out/*_metadata_*.json
cat output.json | bb-conformance -          # read from stdin
```

**2. Python**

```python
from conformance import validate

problems = validate(envelope)   # envelope is a dict
if not problems:
    print("valid")
else:
    for p in problems:
        print(p.path, p.message)
```

**3. Pytest** — the fixture-driven suite `tests/test_conformance.py` drives the same
`validate()` against valid and invalid example envelopes.

## Exit codes (CLI)

| Code | Meaning |
|------|---------|
| `0`  | Valid — the envelope conforms. |
| `1`  | Invalid — one or more conformance problems (each printed with its JSON path). |
| `2`  | Could not read the input, or it was not valid JSON (distinct from a well-formed but non-conforming envelope). |

## Modes

| Flag | What it does |
|------|--------------|
| `--strict` | Also reject unknown/typo fields (`additionalProperties: false`) **and** enforce "success implies output" — if `qc.analysis_pass` is `true`, `objects` and `traits_emitted` must be non-empty. Use it for a tighter internal bar. |
| `--pipeline-output` | Allow the module-injected fields `job_id` and `derived_images` to be absent, so you can validate a pipeline's **raw stdout** before it passes through the module. |
| `--quiet` | Print nothing; communicate via exit code only (handy in CI gates). |

## What counts as valid

In plain terms, a conforming envelope:

- carries `schema_version` `"1.0"`, a `pipeline` (`name` + `version`), a `job_id`, a
  `qc` block, `traits_emitted`, `objects`, and `derived_images`;
- has `qc.analysis_pass` present as a boolean — **how** a pipeline decides pass/fail
  is its own business and is never encoded here;
- names every trait key as `Human Label|IMGSTAT:NNNNNNN` (a 7-digit IMGSTAT id);
- gives every trait both a `value` and a `unit` **key** — either may be `null`
  (dimensionless traits legitimately have `unit: null`; a failed measurement may have
  `value: null`);
- may fail cleanly: `qc.analysis_pass: false` with empty `objects`/`traits_emitted` is
  valid, and an object whose contour detection failed may carry `bbox: null`;
- may add any extra fields it likes (they pass unless you run `--strict`).

The precise, authoritative definition is **[`envelope.schema.json`](./envelope.schema.json)** —
this list is a reader's summary, not a second source of truth.

## More

- Repo overview and the pipeline contract: [`../README.md`](../README.md)
- Pipeline authoring requirements: `docs/PIPELINE_REQUIREMENTS.md` *(planned — not yet written)*

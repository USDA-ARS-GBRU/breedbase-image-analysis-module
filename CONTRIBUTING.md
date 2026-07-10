<!--
  DRAFT CONTRIBUTING.md — review the bracketed [TODO] placeholders before publishing.
  Written to be understood by both software developers and non-developers (breeders, biologists).
-->

# Contributing

Thank you for your interest in improving this project. This is an **open standard** for turning plant images into breeding data, and it is meant to grow through community contributions. Whether you write code or not, there is a way for you to help.

This guide is written for everyone — you do **not** need to be a programmer to contribute. The first section explains the ideas in plain language; later sections get more technical for those building software.

---

## The big picture (start here)

This project does two things:

1. It defines a **standard** — an agreed-upon "shape" for the results any image analysis tool sends back, so that a breeding database (BreedBase) can store results from *any* compliant tool without custom work.
2. It provides one **working example** — the seed morphometry pipeline — that follows the standard.

Think of the standard like a shipping container: it doesn't matter what's inside (seed measurements, leaf measurements, disease scores) — as long as it's packed into the same standard container, the receiving system knows how to handle it. A "pipeline" is any tool that measures something from an image and packs its results into that container.

**Where you fit in:**

- If you **use** the tool and hit a problem or have an idea → [report an issue](#reporting-issues-and-suggesting-ideas). This is valuable and requires no coding.
- If you have **domain knowledge** (a breeder or biologist) → help improve documentation, suggest traits worth measuring, or clarify wording. See [Contributing without writing code](#contributing-without-writing-code).
- If you **build image analysis tools** → build a pipeline that follows the standard. See [Building a compliant pipeline](#building-a-compliant-pipeline).
- If you want to **improve this repository itself** → fix bugs, add features, improve tests. See [Contributing code to this repository](#contributing-code-to-this-repository).

---

## Ways to contribute

### Reporting issues and suggesting ideas

Anyone can do this, and it genuinely helps. If something is confusing, broken, or missing:

1. Go to the repository's **Issues** tab on GitHub.
2. Check whether someone has already reported the same thing (a quick search saves duplicates).
3. Open a new issue and describe what you expected, what happened instead, and — if relevant — the image or command you used.

Good things to report: unclear instructions, a result that looks wrong, a feature you wish existed, or a trait you think the pipeline should measure. You do not need to propose a solution; describing the problem clearly is enough.

### Contributing without writing code

Non-code contributions are welcome and important, especially from breeders and biologists who understand the science:

- **Improve the documentation.** If a section of the README or wiki confused you, an edit that makes it clearer will help the next person. You can suggest changes directly on GitHub without installing anything.
- **Suggest traits or crops.** If there is a measurement or crop the community would benefit from, open an issue describing it and why it matters.
- **Share example images.** Well-photographed sample images (with permission to share) help others learn the correct setup and help us test the software.
- **Review the plain-language docs.** Tell us where the wording assumes too much background knowledge.

### Contributing code to this repository

For fixes and improvements to the framework or the reference pipeline, see [Development setup](#development-setup) and [Submitting a change](#submitting-a-change-pull-requests) below.

### Building a compliant pipeline

If you are creating your own image analysis tool to plug into BreedBase, see [Building a compliant pipeline](#building-a-compliant-pipeline). Your tool can live in its own repository — it just needs to follow the standard.

---

## Development setup

*(This section is for people who will run or edit the code. If that's not you, skip it.)*

**Prerequisites:** Python 3.9 or higher and `pip`.

```bash
# 1. Get the code
git clone https://github.com/USDA-ARS-GBRU/breedbase-image-analysis-module
cd breedbase-image-analysis-module

# 2. Install in "editable" mode with development tools
pip install -e ".[api]"

# 3. Confirm it works
bb-analyze --help

# 4. Run the tests
pytest
```

If `bb-analyze` is "not found," make sure your Python environment's `bin` (or `Scripts` on Windows) directory is on your `PATH`.

---

## Building a compliant pipeline

A pipeline is "compliant" when its output follows the standard — the same JSON structure every other pipeline uses (documented as the *output envelope* in the README). BreedBase can then store your results with no extra work.

### What "compliant" means, in short

Your pipeline must return results that:

- include the required fields (`pipeline.name`, `pipeline.version`, `qc`, `objects`, `traits_emitted`);
- name every trait in the standard `Human-readable name|ONTOLOGY:ID` format;
- attach an explicit **value and unit** to every measurement (never leave units implied);
- report honest quality-control flags — `qc.analysis_pass` must be `true` only when the result is trustworthy;
- produce the **same output for the same input** (determinism).

Extra, pipeline-specific fields are **welcome** — for example, your own quality-control flags. The standard checks that the required parts are present and correctly formed; it does not stop you from adding more. *(See [How compliance is checked](#how-compliance-is-checked) for what is and isn't enforced.)*

### Steps to build one

1. Read `docs/PIPELINE_REQUIREMENTS.md` (the full specification) and study the seed morphometry pipeline in this repository — it is the model to copy.
2. Follow the recommended repository structure in the README. In practice you reuse the `api/` folder and the API contract as-is, and you write only your analysis logic (`process_image.py` and the modules under `pipelines/`).
3. Make sure every item in the [compliance checklist](#compliance-checklist) is satisfied.
4. Verify your output with the conformance check *(see below)* before sharing it.
5. To have your pipeline listed in the community registry, open an issue using the "Propose a pipeline" template. [TODO: confirm the registry/listing process once defined.]

### Compliance checklist

- [ ] Deterministic — the same image and parameters always produce the same output
- [ ] All trait values include explicit units
- [ ] `pipeline.name` and `pipeline.version` present in every result
- [ ] `qc.analysis_pass` accurately reflects reliability
- [ ] No hard-coded file paths
- [ ] Output written only to the designated output directory
- [ ] Installable as a Python package or runnable as a Docker container

### How compliance is checked

Compliance is verified with a **conformance check** — a small tool that reads your pipeline's output and confirms it matches the standard, then reports a clear pass/fail with any specific problems (for example, "object obj_003 is missing a unit").

The check follows a **"strict on the essentials, flexible on extras"** rule:

- **Strictly enforced:** every required field is present and the right type; trait keys use the `Name|ONTOLOGY:ID` format; every trait has an explicit value and unit; required QC flags exist.
- **Allowed and encouraged:** additional pipeline-specific fields (such as custom QC flags). These are passed through and will not cause a failure.

The conformance check validates **structure**, not scientific accuracy — confirming your results are correctly *packaged* is your first step, but making sure they are correct is still your responsibility as the pipeline author.

> **Status:** the conformance check tool is being added to this repository. [TODO: replace this note with the exact command — e.g., `bb-conformance path/to/output.json` — and a link, once the conformance stub is merged.]

> **Note on the standard's source of truth:** the API contract lives in `config/openapi.yml`, and the conformance check uses a JSON Schema describing the output envelope. These two should agree. [TODO: if `openapi.yml` fully specifies the nested envelope, derive the schema from it so there is a single source of truth; otherwise keep the standalone schema in sync with a test.]

---

## Submitting a change (pull requests)

*(For code and documentation edits made through GitHub.)*

1. **Fork** the repository and create a branch with a descriptive name (e.g., `fix-color-card-detection`).
2. **Make your change.** Keep it focused — one logical change per pull request is easier to review.
3. **Add or update tests** if you changed behavior. New pipelines and features should include a test proving they work.
4. **Run the checks locally** before submitting:
   ```bash
   pytest
   ```
   [TODO: add any linting/formatting commands the project uses, e.g., `black .`, `ruff check .`.]
5. **Open a pull request** describing what you changed and why. Link any related issue.
6. A maintainer will review it. Expect a friendly back-and-forth — questions and requested tweaks are a normal part of the process, not a rejection. [TODO: state expected review turnaround if you want to set expectations.]

### What makes a pull request easy to accept

- It does one thing, clearly described.
- Tests pass and new behavior is covered by a test.
- Output stays deterministic and units stay explicit.
- Version numbers follow [semantic versioning](https://semver.org) (e.g., `1.2.0`), and user-facing changes are noted in the changelog. [TODO: add a `CHANGELOG.md` or state your changelog convention.]

---

## Versioning

This project uses [semantic versioning](https://semver.org): `MAJOR.MINOR.PATCH`. Increase MAJOR for changes that break compatibility with the standard, MINOR for backward-compatible additions, and PATCH for fixes. Every pipeline result must report its own `pipeline.version` so results can always be traced back to the exact code that produced them.

---

## Code of conduct

We want this to be a welcoming, respectful community for contributors of every background and experience level. Please be kind and constructive in issues, reviews, and discussions. [TODO: add a `CODE_OF_CONDUCT.md` — the [Contributor Covenant](https://www.contributor-covenant.org) is a common, ready-made choice — and link it here.]

---

## License and attribution

By contributing, you agree that your contributions will be licensed under the project's license. [TODO: state the project license once chosen — e.g., MIT / BSD-3-Clause / Apache-2.0 — and add whether a Developer Certificate of Origin (DCO) sign-off is required on commits.]

---

## Questions?

If anything here is unclear, open an issue with the "question" label — asking is itself a useful contribution, because it shows us where the documentation can be better. [TODO: add a maintainer contact or discussion-forum link if you have one.]

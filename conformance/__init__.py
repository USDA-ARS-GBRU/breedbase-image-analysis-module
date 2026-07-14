"""BreedBase image-analysis output conformance kit.

`envelope.schema.json` is the normative contract for the canonical output envelope;
`validate()` (and the `bb-conformance` CLI) check an envelope against it. See
`conformance/README.md` for usage. This file exists so `conformance` is an importable
package — which lets `validate.py` load the schema as package data via
`importlib.resources.files("conformance")`, and lets callers do
`from conformance import validate`.
"""
from .validate import Problem, main, validate

# Kit version. Deliberately DISTINCT from the envelope's `schema_version` ("1.0"):
# this versions the checker tool; `schema_version` versions the payload shape. They
# move independently.
__version__ = "0.1.0"

__all__ = ["validate", "main", "Problem", "__version__"]

# Small comparison sources

These four closed-subset programs provide hand-checkable semantic expectations:
`original.c`, `renamed.c` and `refactored.c` return 16*16+1 = 257; `unrelated.c`
returns 7. Renaming changes a local name; refactoring adds an assignment. Each
calculation fits signed 32-bit C arithmetic. This reasoning is independent of a
fingerprint score. They are not a held-out classification corpus or a vendor
identification evaluation, and no runtime measurements are supplied for them.

Inspect actual pure transformation structure without running a benchmark:

```sh
python -m compiler --tac examples/comparison/refactored.c
python -m compiler --transform constants --tac examples/comparison/refactored.c
```

Existing genuine compiler/timing evidence is reused from
[`../observations/phase5/`](../observations/phase5/README.md). Phase 6 comparisons
of those reports preserve failures, source/configuration identities, unreliable
runtime values and exclusions. Different programs require explicit `program`
alignment and the same pipeline/configuration; different structures must not be
called different compiler behavior. Similar profiles do not establish equivalent
programs. The Phase 7 dashboard, baseline evaluation and classifiers are absent.

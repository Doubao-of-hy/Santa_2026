# Incumbent-only DAG reselection

Place `scc_select.py` at the project root beside `elf.py`; the
existing `generative/` modules are imported from that same checkout.
Use Python 3.12+ and OR-Tools (tested with 9.15.6755).

```bash
python -B scc_select.py data/puzzles.csv submission.csv candidate.csv --ids-file ids.txt --seconds 2.75 --jobs 5
```

Omit `--ids-file` to cover all input cases. By default, the solver uses only
values present in the incumbent's active arithmetic graph. Its recipes
are equalities obtained by legal arithmetic on those known values.
It models joint sharing across all targets. Any cycle in the union
of recipe choices must be contained within a strongly connected
component, so only within-component edges need strict rank
constraints. Every operand of a selected recipe must itself be
selected or be an initial value.

Add `--translation-offsets` to admit screened shared differences between
existing values. Each new difference must have its own legal recipe and
counts as an arithmetic node if chosen. This is optional and does not
change what the finite-bank bounds mean.

`OPTIMAL` and `finite_bank_node_lower_bound` refer only to the count
of distinct arithmetic nodes in this finite recipe bank. They are
**not** global puzzle bounds, and the register constraints are imposed
by the subsequent compiler and interpreter replay, not the CP-SAT model.
A smaller arithmetic graph that fails to produce a shorter legal tape
does not replace the incumbent. A final complete candidate is replayed
by both interpreters before saving to a new filename. No network,
official submission, or existing CSV update is performed.

# Single-parent recipe recombination

Arsen Zakaryan’s version 15 supplies the recombiner, recipe builder and register-machine replay. The local `paid_helpers.py` adds candidate values ranked by how many predecessor operations can be removed. Each candidate program is replayed before writing. The output CSV contains one puzzle. Use a new output filename. [Upstream license](LICENSE) · [Source version and hashes](SOURCE.json) · [Full search results](../../collaboration/methods.md)

With Python and OR-Tools installed, run from the repository root.

```powershell
python -B generative/arsen_v15/paid_helpers.py data/puzzles.csv submission.csv scored_0710 new-0710.csv
```

import json
import unittest
from contextlib import closing

from elf import Puzzle, replay
from model_rewrite import already_certified, open_ledger, pending, reserve, verified_edit, windows


class ModelRewriteTests(unittest.TestCase):
    def setUp(self):
        self.puzzle = Puzzle("example", (2, 3), (4, 24), 100, 6)
        self.program = (
            ("+", 0, 0, 2),  # sole occurrence of 4
            ("+", 2, 0, 3),
            ("+", 3, 0, 3),
            ("/", 3, 3, 4),
            ("*", 3, 1, 3),  # read register 3 before overwriting it
        )
        self.window = next(w for _, w in windows(self.puzzle, self.program,
                                                replay(self.puzzle, self.program)))

    def test_shorter_edit_preserves_target_hits_and_suffix_reads(self):
        self.assertEqual(self.window.data["hit"], [4])
        self.assertEqual(self.window.data["end"], [(1, 3), (3, 8)])
        answer = '{"steps":[["+",0,0,2],["*",2,0,3]]}'
        candidate = verified_edit(self.puzzle, self.program, self.window, answer)
        self.assertEqual(len(candidate), 3)
        self.assertEqual(candidate[-1], self.program[-1])

    def test_requires_exact_boundary_and_rejects_invalid_indices(self):
        for steps in ([['+', 0, 0, 2]], [['+', True, 0, 2]], [['*', 0, 1, 7]],
                      [['+', 1, 1, 3], ['+', 3, 0, 3]]):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                verified_edit(self.puzzle, self.program, self.window, json.dumps({"steps": steps}))
        self.assertIsNone(verified_edit(self.puzzle, self.program, self.window, '{"steps":null}'))

    def test_deduplication_budget_and_known_bounds(self):
        identifier = self.puzzle.id
        with closing(open_ledger(":memory:")) as db:
            self.assertEqual(list(pending(db, [self.puzzle], {identifier: self.program},
                                          {identifier: len(self.program)}, {})), [])
            self.assertEqual(list(pending(db, [self.puzzle], {identifier: self.program},
                                          {}, {identifier: len(self.program) - 1})), [])
            self.assertEqual(reserve(db, self.window.key, "dataset", identifier, 2), "reserved")
            self.assertEqual(reserve(db, self.window.key, "other", "other", 2), "duplicate")
            self.assertEqual(reserve(db, "other", "dataset", identifier, 2), "reserved")
            self.assertEqual(reserve(db, "third", "dataset", identifier, 2), "budget")

    def test_proven_window_can_have_more_inputs_and_fewer_targets(self):
        self.assertTrue(already_certified(self.window, [(4, {1, 2, 3}, {8})]))
        self.assertFalse(already_certified(self.window, [(4, {2}, {8})]))
        self.assertFalse(already_certified(self.window, [(4, {1, 2, 3}, {6, 8})]))
        self.assertFalse(already_certified(self.window, [(3, {1, 2, 3}, {8})]))


if __name__ == "__main__":
    unittest.main()

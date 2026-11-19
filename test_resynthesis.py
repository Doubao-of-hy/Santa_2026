"""Regression fixtures for shared-node deletion and exact-integer synthesis."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from machine import Puzzle, replay
from resynthesize import optimize
from seed_construct import solve


class CheckpointTests(unittest.TestCase):
    def test_replacement_offsets_refer_to_original_program(self):
        from checkpoint_patch import apply_edits, edits

        before = [["+", 0, 0, 3], ["*", 3, 0, 2], ["-", 2, 3, 2], ["+", 2, 2, 1]]
        after = [["/", 0, 0, 1], before[0], before[2], ["*", 2, 0, 0]]
        self.assertEqual(apply_edits(before, edits(before, after)), after)
        with self.assertRaises(ValueError):
            apply_edits(before, [[2, 3, []], [1, 2, []]])


@unittest.skipUnless(
    shutil.which(os.environ.get("CXX", "g++")), "C++17 compiler required"
)
class NativeSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.bin = {}
        for engine in ("eviction", "seed_search"):
            path = Path(cls.tmp.name) / engine
            subprocess.run(
                [
                    os.environ.get("CXX", "g++"),
                    "-std=c++17",
                    "-O1",
                    str(Path(__file__).with_name(engine + ".cpp")),
                    "-o",
                    str(path),
                ],
                check=True,
            )
            cls.bin[engine] = str(path)

    def test_shared_intermediate_can_be_removed_jointly(self):
        puzzle = Puzzle("shared", (2, 3, 5, 7, 8), (12, 13), 20, 8)
        code = [["+", 1, 1, 5], ["+", 5, 5, 6], ["+", 5, 3, 7]]
        _, better = optimize(puzzle, code, self.bin["eviction"], 7, 0, 4, 0, 0)
        self.assertEqual(replay(puzzle, better), 2)

    def test_quotient_search_near_machine_limit(self):
        # Multiplying the two starting values exceeds the allowed machine range.
        p = Puzzle(
            "bounds",
            (999999999999999997, 999999999999999993),
            (4, 999999999999999989),
            10**18,
            10,
        )
        _, best = solve((p, self.bin["seed_search"], 12, 4, None, True))
        self.assertEqual(replay(p, best), 2)

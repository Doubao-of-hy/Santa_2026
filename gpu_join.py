"""Search calculator dependency cuts with a fused OpenCL 3-vs-2 join."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from math import isqrt
from pathlib import Path
from time import perf_counter

import numpy as np

from elf import Program, Puzzle, arithmetic, check, read_puzzles, read_submission, score, write_submission
from graph import Graph, active_graph, compile_graph, first_recipes
from gpu_schedule import schedule_like


ROOT = Path(__file__).resolve().parent
OPERATORS = " +-*/"


@dataclass
class Table:
    values: np.ndarray
    operators: np.ndarray
    left: np.ndarray
    right: np.ndarray
    n0: int
    n1: int


@dataclass
class DevicePool:
    table: Table
    buffers: list
    short_slots: object
    short_mask: int
    raw: object
    long_slots: object
    long_mask: int
    raw_count: int


@dataclass(frozen=True)
class Reduction:
    quotient: int
    scale: int
    residual: int
    sign: int
    overhead: int


def generated(values, indices, others, limit):
    """Vectorized arithmetic with a witness for each generated output."""
    first, second = values[indices], values[others]
    swap = first < second
    a, b = np.maximum(first, second), np.minimum(first, second)
    left = np.where(swap, others, indices).astype(np.uint32)
    right = np.where(swap, indices, others).astype(np.uint32)
    allowed_product = a <= np.uint64(limit) // b
    masks = (a + b <= limit, a > b, allowed_product, a % b == 0)
    outputs = (a + b, a - b, a * b, a // b)
    result = [out[mask] for out, mask in zip(outputs, masks)]
    choices = np.concatenate(result)
    witnesses = np.concatenate([np.full(np.count_nonzero(mask), op, dtype=np.uint8)
                                for op, mask in enumerate(masks, 1)])
    l = np.concatenate([left[mask] for mask in masks])
    r = np.concatenate([right[mask] for mask in masks])
    unique, source = np.unique(choices, return_index=True)
    return unique, witnesses[source], l[source], r[source]


def make_table(anchors: tuple[int, ...], limit: int) -> Table:
    seeds = np.array(sorted(set(anchors)), dtype=np.uint64)
    left, right = np.triu_indices(len(seeds))
    first, first_ops, first_left, first_right = generated(seeds, left, right, limit)
    new = ~np.isin(first, seeds)
    first = first[new]
    n0, n1 = len(seeds), len(seeds) + len(first)
    known = np.concatenate((seeds, first))
    first_indices = np.arange(n0, n1, dtype=np.uint32)
    seed_indices = np.arange(n0, dtype=np.uint32)
    l = np.concatenate((np.repeat(first_indices, len(seeds)), first_indices))
    r = np.concatenate((np.tile(seed_indices, len(first)), first_indices))
    second, second_ops, second_left, second_right = generated(known, l, r, limit)
    new_second = ~np.isin(second, known)
    return Table(
        np.concatenate((known, second[new_second])),
        np.concatenate((np.zeros(n0, dtype=np.uint8), first_ops[new], second_ops[new_second])),
        np.concatenate((np.zeros(n0, dtype=np.uint32), first_left[new], second_left[new_second])),
        np.concatenate((np.zeros(n0, dtype=np.uint32), first_right[new], second_right[new_second])),
        n0,
        n1,
    )


class GPUJoin:
    def __init__(self, directory: Path, software: bool = False):
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        deps = ROOT / "work" / "gpu" / "deps"
        if deps.is_dir():
            sys.path.insert(0, str(deps))
        cache = directory / "cl-cache"
        driver_cache = directory / "driver-cache"
        temporary = directory / "temp"
        for path in (cache, driver_cache, temporary):
            path.mkdir(exist_ok=True)
        os.environ["CUDA_CACHE_PATH"] = str(driver_cache)
        os.environ["PYOPENCL_CACHE_DIR"] = str(cache)
        os.environ["TEMP"] = os.environ["TMP"] = str(temporary)
        import pyopencl as cl

        self.cl = cl
        devices = [device for platform in cl.get_platforms() for device in platform.get_devices()
                   if device.type & cl.device_type.GPU or software]
        if not devices:
            raise RuntimeError("No OpenCL device found")
        self.device = min(devices, key=lambda d: ("5070" not in d.name, "NVIDIA" not in d.vendor))
        self.context = cl.Context([self.device])
        self.queue = cl.CommandQueue(self.context, properties=cl.command_queue_properties.PROFILING_ENABLE)
        source = Path(__file__).resolve().with_suffix(".cl").read_text(encoding="utf-8")
        self.program = cl.Program(self.context, source).build(options=("-cl-std=CL1.2",),
                                                              cache_dir=str(cache))
        self.insert = cl.Kernel(self.program, "insert_table")
        self.two = cl.Kernel(self.program, "join_two")
        self.three = cl.Kernel(self.program, "join_three")
        self.materialize = cl.Kernel(self.program, "materialize_three")
        self.insert_unique = cl.Kernel(self.program, "insert_unique")
        self.seven = cl.Kernel(self.program, "join_seven")
        self.affine_near = cl.Kernel(self.program, "affine_near")
        self.affine_residues = cl.Kernel(self.program, "affine_residues")

    @staticmethod
    def rounded(size):
        return ((size + 255) // 256) * 256

    @staticmethod
    def duration(event) -> float:
        return (event.profile.end - event.profile.start) * 1e-9

    def search(self, table: Table, target: int, limit: int, budget: int, capacity: int):
        cl = self.cl
        count = len(table.values)
        slots = 1 << ((count * 2 - 1).bit_length())
        flags = cl.mem_flags
        arrays = [cl.Buffer(self.context, flags.READ_ONLY | flags.COPY_HOST_PTR, hostbuf=x)
                  for x in (table.values, table.left, table.right)]
        values, left, right = arrays
        hashed = cl.Buffer(self.context, flags.READ_WRITE, size=slots * 4)
        counts = np.zeros(8, dtype=np.uint32)
        records = np.zeros((8, capacity, 6), dtype=np.uint32)
        device_counts = cl.Buffer(self.context, flags.READ_WRITE | flags.COPY_HOST_PTR, hostbuf=counts)
        device_records = cl.Buffer(self.context, flags.WRITE_ONLY, size=records.nbytes)
        cl.enqueue_fill_buffer(self.queue, hashed, np.uint32(0), 0, slots * 4)
        insertion = self.insert(self.queue, (self.rounded(count),), None, values,
                                np.uint32(count), np.uint32(slots - 1), hashed)
        fields = (np.uint32(table.n0), np.uint32(table.n1), np.uint32(count),
                  np.uint32(slots - 1), np.uint64(target), np.uint64(limit),
                  np.uint32(min(6, budget)), np.uint32(capacity), device_counts, device_records)
        two = self.two(self.queue, (self.rounded(count),), None, values, hashed, *fields)
        first_count = table.n1 - table.n0
        second_count = count - table.n1
        work = second_count * (table.n0 + 3) + first_count * first_count
        event = None
        if budget >= 3 and work:
            event = self.three(self.queue, (self.rounded(work),), None,
                               values, hashed, left, right, *fields)
        cl.enqueue_copy(self.queue, counts, device_counts)
        cl.enqueue_copy(self.queue, records, device_records).wait()
        matches = [tuple(map(int, row)) for kinds in range(1, 7)
                   for row in records[kinds, :min(capacity, int(counts[kinds]))]]
        times = {"hash": self.duration(insertion), "two": self.duration(two),
                 "three": self.duration(event) if event is not None else 0,
                 "pairs": work if event is not None else 0}
        if budget >= 7 and work:
            further, depth = self.join_seven(table, target, limit, capacity, work, arrays)
            matches.extend(further)
            times.update(depth)
        return matches, times

    def join_seven(self, table, target, limit, capacity, pairs, arrays):
        bank = self.build_raw_bank(table, limit, pairs, arrays)
        if bank is None:
            return [], {"seven_skips": 1}
        raw, hashed, count, mask, timing = bank
        cl = self.cl
        flags = cl.mem_flags
        counts = np.zeros(8, dtype=np.uint32)
        records = np.zeros((8, capacity, 6), dtype=np.uint32)
        device_counts = cl.Buffer(self.context, flags.READ_WRITE | flags.COPY_HOST_PTR, hostbuf=counts)
        device_records = cl.Buffer(self.context, flags.WRITE_ONLY, size=records.nbytes)
        probes = []
        chunk = 2**21
        for at in range(0, count, chunk):
            global_size = (self.rounded(min(chunk, count - at)),)
            probes.append(self.seven(self.queue, global_size, None, raw, hashed,
                                     np.uint32(count), np.uint32(mask), np.uint32(at),
                                     np.uint64(target), np.uint64(limit), np.uint32(capacity),
                                     device_counts, device_records))
        cl.enqueue_copy(self.queue, counts, device_counts)
        cl.enqueue_copy(self.queue, records, device_records).wait()
        matches = [tuple(map(int, row)) for row in records[7, :min(capacity, int(counts[7]))]]
        timing["seven"] = sum(self.duration(event) for event in probes)
        return matches, timing

    def build_raw_bank(self, table, limit, pairs, arrays):
        count = 4 * pairs
        if count == 0:
            return None
        slots = 1 << ((count * 2 - 1).bit_length())
        max_allocation = self.device.max_mem_alloc_size
        if (count >= 2**32 or max(count * 8, slots * 4) > max_allocation
                or count * 8 + slots * 4 > min(2500 * 1024**2, self.device.global_mem_size // 3)):
            return None
        cl = self.cl
        flags = cl.mem_flags
        raw = cl.Buffer(self.context, flags.READ_WRITE, size=count * 8)
        hashed = cl.Buffer(self.context, flags.READ_WRITE, size=slots * 4)
        values, left, right = arrays
        make = self.materialize(self.queue, (self.rounded(pairs),), None,
                                values, left, right,
                                np.uint32(table.n0), np.uint32(table.n1), np.uint32(len(table.values)),
                                np.uint32(pairs), np.uint64(limit), raw)
        cl.enqueue_fill_buffer(self.queue, hashed, np.uint32(0), 0, slots * 4)
        inserted = []
        chunk = 2**21
        for at in range(0, count, chunk):
            global_size = (self.rounded(min(chunk, count - at)),)
            inserted.append(self.insert_unique(self.queue, global_size, None, raw,
                                               np.uint32(count), np.uint32(slots - 1), np.uint32(at),
                                               hashed))
        inserted[-1].wait()
        return raw, hashed, count, slots - 1, {"materialize": self.duration(make),
                                               "hash3": sum(self.duration(event) for event in inserted),
                                               "raw3": count}

    def prepare_pool(self, table: Table, limit: int, raw_table: Table | None = None):
        cl = self.cl
        flags = cl.mem_flags
        count = len(table.values)
        slots = 1 << ((count * 2 - 1).bit_length())
        arrays = [cl.Buffer(self.context, flags.READ_ONLY | flags.COPY_HOST_PTR, hostbuf=x)
                  for x in (table.values, table.left, table.right)]
        short = cl.Buffer(self.context, flags.READ_WRITE, size=slots * 4)
        cl.enqueue_fill_buffer(self.queue, short, np.uint32(0), 0, slots * 4)
        inserted = self.insert(self.queue, (self.rounded(count),), None, arrays[0],
                               np.uint32(count), np.uint32(slots - 1), short)
        raw_table = table if raw_table is None else raw_table
        raw_arrays = arrays if raw_table is table else [
            cl.Buffer(self.context, flags.READ_ONLY | flags.COPY_HOST_PTR, hostbuf=x)
            for x in (raw_table.values, raw_table.left, raw_table.right)]
        pairs = ((len(raw_table.values) - raw_table.n1) * (raw_table.n0 + 3)
                 + (raw_table.n1 - raw_table.n0) ** 2)
        bank = self.build_raw_bank(raw_table, limit, pairs, raw_arrays)
        inserted.wait()
        timing = {"hash": self.duration(inserted), "pairs": pairs}
        if bank is None:
            raw, long, raw_count, long_mask = arrays[0], short, 0, 0
            timing["long_skips"] = 1
        else:
            raw, long, raw_count, long_mask, clocks = bank
            timing.update(clocks)
        return DevicePool(table, arrays, short, slots - 1, raw, long, long_mask, raw_count), timing

    def query_affine(self, pool, target, limit, budget, capacity, radius, atoms, raw_scales):
        cl = self.cl
        flags = cl.mem_flags
        table = pool.table
        scales = scale_roster(table, target, atoms)
        if not scales:
            return [], {}
        counts = np.zeros(11, dtype=np.uint32)
        records = np.zeros((11, capacity, 6), dtype=np.uint32)
        device_counts = cl.Buffer(self.context, flags.READ_WRITE | flags.COPY_HOST_PTR, hostbuf=counts)
        device_records = cl.Buffer(self.context, flags.WRITE_ONLY, size=records.nbytes)
        scale_buffer = cl.Buffer(self.context, flags.READ_ONLY | flags.COPY_HOST_PTR,
                                 hostbuf=np.array(scales, dtype=np.uint32))
        bank = (pool.buffers[0], pool.short_slots, pool.raw, pool.long_slots,
                np.uint32(table.n0), np.uint32(table.n1), np.uint32(pool.short_mask),
                np.uint32(pool.long_mask))
        requirements = (np.uint64(target), np.uint64(limit), np.uint32(budget),
                        np.uint32(capacity), device_counts, device_records)
        near = self.affine_near(self.queue, (self.rounded(len(scales) * (2 * radius + 1)),),
                                None, *bank, scale_buffer, np.uint32(len(scales)), np.uint32(radius),
                                *requirements)
        short_work = len(scales) * len(table.values)
        chunk = 2**22
        exact = []
        for at in range(0, short_work, chunk):
            exact.append(self.affine_residues(self.queue,
                                              (self.rounded(min(chunk, short_work - at)),), None,
                                              *bank, scale_buffer, np.uint32(len(scales)),
                                              np.uint32(len(table.values)), np.uint32(at), np.uint32(0),
                                              *requirements))
        long_work = 0
        long_events = []
        if pool.raw_count and raw_scales > 0 and budget >= 6:
            width = target.bit_length()
            lifted = sorted(scales, key=lambda i: (
                abs(int(table.values[i]).bit_length() - width * 0.50) + (i >= table.n0),
                i,
            ))[:raw_scales]
            raw_scale_buffer = cl.Buffer(self.context, flags.READ_ONLY | flags.COPY_HOST_PTR,
                                         hostbuf=np.array(lifted, dtype=np.uint32))
            long_work = len(lifted) * pool.raw_count
            for at in range(0, long_work, chunk):
                long_events.append(self.affine_residues(self.queue,
                                                        (self.rounded(min(chunk, long_work - at)),),
                                                        None, *bank, raw_scale_buffer,
                                                        np.uint32(len(lifted)), np.uint32(pool.raw_count),
                                                        np.uint32(at), np.uint32(1), *requirements))
        cl.enqueue_copy(self.queue, counts, device_counts)
        cl.enqueue_copy(self.queue, records, device_records).wait()
        matches = [tuple(map(int, row)) for cost in range(1, 11)
                   for row in records[cost, :min(capacity, int(counts[cost]))]]
        timing = {"affine_near": self.duration(near), "affine2": sum(self.duration(event) for event in exact),
                  "affine3": sum(self.duration(event) for event in long_events),
                  "affine2_pairs": short_work, "affine3_pairs": long_work}
        return matches, timing

    def query_balanced(self, pool, target, limit, budget, capacity):
        cl = self.cl
        flags = cl.mem_flags
        table = pool.table
        count = len(table.values)
        values, left, right = pool.buffers
        counts = np.zeros(8, dtype=np.uint32)
        records = np.zeros((8, capacity, 6), dtype=np.uint32)
        device_counts = cl.Buffer(self.context, flags.READ_WRITE | flags.COPY_HOST_PTR, hostbuf=counts)
        device_records = cl.Buffer(self.context, flags.WRITE_ONLY, size=records.nbytes)
        fields = (np.uint32(table.n0), np.uint32(table.n1), np.uint32(count),
                  np.uint32(pool.short_mask), np.uint64(target), np.uint64(limit),
                  np.uint32(min(6, budget)), np.uint32(capacity), device_counts, device_records)
        two = self.two(self.queue, (self.rounded(count),), None, values, pool.short_slots, *fields)
        work = (count - table.n1) * (table.n0 + 3) + (table.n1 - table.n0) ** 2
        three = None
        if budget >= 3 and work:
            three = self.three(self.queue, (self.rounded(work),), None, values,
                               pool.short_slots, left, right, *fields)
        seven = []
        if budget >= 7 and pool.raw_count:
            chunk = 2**22
            for at in range(0, pool.raw_count, chunk):
                seven.append(self.seven(self.queue,
                                        (self.rounded(min(chunk, pool.raw_count - at)),), None,
                                        pool.raw, pool.long_slots, np.uint32(pool.raw_count),
                                        np.uint32(pool.long_mask), np.uint32(at), np.uint64(target),
                                        np.uint64(limit), np.uint32(capacity),
                                        device_counts, device_records))
        cl.enqueue_copy(self.queue, counts, device_counts)
        cl.enqueue_copy(self.queue, records, device_records).wait()
        witnesses = [tuple(map(int, row)) for cost in range(8)
                     for row in records[cost, :min(capacity, int(counts[cost]))]]
        elapsed = self.duration(two) + sum(self.duration(event) for event in seven)
        if three is not None:
            elapsed += self.duration(three)
        return witnesses, elapsed


def scale_roster(table: Table, target: int, atoms: int) -> list[int]:
    base = [i for i in range(table.n0) if 1 < table.values[i] <= target // 2]
    groups: dict[int, list[int]] = {}
    for i in range(table.n0, table.n1):
        value = int(table.values[i])
        if 16 <= value <= target // 2:
            groups.setdefault(value.bit_length(), []).append(i)
    if not atoms or not groups:
        return base
    selected = []
    per_group = max(1, atoms // len(groups))
    for group in groups.values():
        if len(group) <= per_group:
            selected.extend(group)
        elif per_group == 1:
            selected.append(group[len(group) // 2])
        else:
            selected.extend(group[j * (len(group) - 1) // (per_group - 1)]
                            for j in range(per_group))
    return base + selected


def next_reductions(table: Table, target: int, limit: int, budget: int, count: int):
    base = [int(x) for x in table.values[:table.n0]]
    atoms = {value: index for index, value in enumerate(base)}
    projections = set()

    def insert(value, multiplier, residue, direction):
        if value <= 1 or value > limit or value == target or value in atoms:
            return
        expense = int(multiplier >= 0) + int(residue >= 0)
        if expense < budget:
            projections.add(Reduction(value, multiplier, residue, direction, expense))

    for index, residue in enumerate(base):
        if residue < target:
            insert(target - residue, -1, index, 0)
        if target <= limit - residue:
            insert(target + residue, -1, index, 1)
        if residue > target:
            insert(residue - target, -1, index, 2)
    for scale_index, scale in enumerate(base):
        if scale <= 1 or scale > target // 2:
            continue
        if target % scale == 0:
            insert(target // scale, scale_index, -1, 0)
        for residual_index, residue in enumerate(base):
            if residue < target and (target - residue) % scale == 0:
                insert((target - residue) // scale, scale_index, residual_index, 0)
            if target <= limit - residue and (target + residue) % scale == 0:
                insert((target + residue) // scale, scale_index, residual_index, 1)
            if residue > target and (residue - target) % scale == 0:
                insert((residue - target) // scale, scale_index, residual_index, 2)
    factors = sorted((form for form in projections if form.scale >= 0),
                     key=lambda form: (
                         form.quotient.bit_length() / 5 + form.overhead,
                         form.quotient, form.scale, form.residual, form.sign,
                     ))
    translations = sorted((form for form in projections if form.scale < 0),
                          key=lambda form: (
                              form.quotient.bit_length(), abs(target - form.quotient),
                              form.quotient,
                          ))
    selected = (*factors[:max(1, count * 2 // 3)], *translations)
    seen = set()
    ranked = []
    for form in (*selected, *factors):
        if form.quotient not in seen:
            ranked.append(form)
            seen.add(form.quotient)
            if len(ranked) >= count:
                break
    return ranked


def triple_pair(table: Table, slot: int) -> tuple[int, int, int]:
    pair, code = divmod(slot, 4)
    two = len(table.values) - table.n1
    one = table.n1 - table.n0
    pairs20 = two * table.n0
    pairs11 = one * one
    if pair < pairs20:
        left, right = divmod(pair, table.n0)
        left += table.n1
    elif pair < pairs20 + pairs11:
        left, right = divmod(pair - pairs20, one)
        left += table.n0
        right += table.n0
    else:
        left, mode = divmod(pair - pairs20 - pairs11, 3)
        left += table.n1
        right = (left, int(table.left[left]), int(table.right[left]))[mode]
    if table.values[left] < table.values[right]:
        left, right = right, left
    return code + 1, left, right


def decode(anchors: tuple[int, ...], table: Table, record, target: int) -> Graph:
    recipes: Graph = {}
    literals = set(anchors)

    def realize(index: int) -> int:
        value = int(table.values[index])
        if index >= table.n0 and value not in recipes:
            code = OPERATORS[table.operators[index]]
            left = realize(int(table.left[index]))
            right = realize(int(table.right[index]))
            recipes[value] = code, left, right
        return value

    def realize_triple(code, i, j):
        a, b = realize(i), realize(j)
        op = OPERATORS[code]
        intermediate = arithmetic(op, a, b)
        if intermediate not in literals:
            recipes.setdefault(intermediate, (op, a, b))
        return intermediate

    def realize_encoded(index: int):
        if index & 0x80000000:
            return realize_triple(*triple_pair(table, index & 0x7fffffff))
        return realize(index)

    code, i, j, root, reverse, other = record
    if code == 6:
        scale, quotient = realize(i), realize_encoded(j)
        product = scale * quotient
        if product not in literals:
            recipes.setdefault(product, ("*", scale, quotient))
        if root != 0xffffffff:
            residual = realize_encoded(root)
            if reverse == 0:
                recipe = "+", product, residual
            elif reverse == 1:
                recipe = "-", product, residual
            else:
                recipe = "-", residual, product
            if arithmetic(*recipe) != target:
                raise RuntimeError("GPU affine witness does not evaluate to target")
            recipes[target] = recipe
        elif product != target:
            raise RuntimeError("GPU affine product does not evaluate to target")
        return recipes
    if code == 5:
        intermediate = realize_triple(*triple_pair(table, i))
        complement = realize_triple(*triple_pair(table, j))
    elif code:
        intermediate = realize_triple(code, i, j)
    else:
        intermediate = realize(i)
    if root:
        if code != 5:
            complement = realize(other)
        op = OPERATORS[root]
        left, right = (complement, intermediate) if reverse else (intermediate, complement)
        if arithmetic(op, left, right) != target:
            raise RuntimeError("GPU witness does not evaluate to the target")
        recipes[target] = op, left, right
    elif intermediate != target:
        raise RuntimeError("GPU subtree witness does not evaluate to the target")
    return recipes


def lift_reduction(table: Table, partial: Graph, choice: Reduction, target: int) -> Graph:
    recipes = partial.copy()
    product = choice.quotient
    if choice.scale >= 0:
        factor = int(table.values[choice.scale])
        product *= factor
        recipes.setdefault(product, ("*", choice.quotient, factor))
    if choice.residual >= 0:
        residue = int(table.values[choice.residual])
        if choice.sign == 0:
            recipe = "+", product, residue
        elif choice.sign == 1:
            recipe = "-", product, residue
        else:
            recipe = "-", residue, product
        if arithmetic(*recipe) != target:
            raise RuntimeError("reverse reduction returned an invalid expression")
        recipes[target] = recipe
    elif product != target:
        raise RuntimeError("reverse product returned an invalid expression")
    return recipes


def cut_many(puzzle: Puzzle, graph: Graph, pivots: set[int]) -> tuple[Graph, Graph]:
    stops = set(puzzle.seeds) | pivots
    needed = set()
    pending = list(set(puzzle.targets) - stops)
    while pending:
        value = pending.pop()
        if value in stops or value in needed:
            continue
        needed.add(value)
        pending.extend(graph[value][1:])
    surviving = {value: edge for value, edge in graph.items() if value in needed}
    known = set(puzzle.seeds)
    free: Graph = {}
    for value, edge in surviving.items():
        if edge[1] in known and edge[2] in known:
            known.add(value)
            free[value] = edge
    return surviving, free


def cut(puzzle: Puzzle, graph: Graph, pivot: int) -> tuple[Graph, Graph]:
    return cut_many(puzzle, graph, {pivot})


def anchors_for(puzzle: Puzzle, surviving: Graph, free: Graph, pivot: int, quantity: int,
                required=()):
    counts = Counter(child for edge in surviving.values() for child in set(edge[1:]))
    bits = pivot.bit_length()
    seeds = set(puzzle.seeds)
    old_operands = set(puzzle.targets) & free.keys()
    groups = {}
    for value in free:
        length = value.bit_length()
        relevance = 0.0
        if counts[value] > 1:
            relevance += 2.0 * min(15, counts[value])
        if value <= 1024:
            relevance += 4
        if value in old_operands:
            relevance += 1
        if pivot % value == 0:
            relevance += 2
        if abs(value - pivot) <= max(128, pivot // 100):
            relevance += 7
        if abs(length * 2 - bits) <= 5:
            relevance += 2
        groups.setdefault(length // 8, []).append((-relevance, value))
    elected = set(seeds) | set(required)
    # Retain some values on every occupied scale, then fill with commonly used anchors.
    base_quota = max(1, (quantity - len(seeds)) // max(1, 2 * len(groups)))
    for group in groups.values():
        for _, value in sorted(group)[:base_quota]:
            if len(elected) < quantity:
                elected.add(value)
    all_candidates = sorted(item for group in groups.values() for item in group)
    for _, value in all_candidates:
        if len(elected) >= quantity:
            break
        elected.add(value)
    return tuple(sorted(elected))


def shortest_graphs(puzzle: Puzzle, pivot: int, table: Table, anchors, matches, surviving, current,
                    try_overrides=False, supplemental=(), keep_all=False):
    graphs = {}
    arithmetic_plans = [decode(anchors, table, record, pivot) for record in matches]
    arithmetic_plans.extend(supplemental)
    for replacement in arithmetic_plans:
        if pivot not in replacement:
            continue
        default = replacement | surviving | {pivot: replacement[pivot]}
        alternatives = (default, surviving | replacement) if try_overrides else (default,)
        for candidate in alternatives:
            try:
                materialized = active_graph(puzzle, candidate)
            except (KeyError, ValueError):
                continue
            if len(materialized) >= current and not keep_all:
                continue
            identity = frozenset(materialized.items())
            graphs[identity] = materialized
    return sorted(graphs.values(), key=len)


def conditional_anchors(puzzle: Puzzle, graph: Graph, pending: list[int], ordinary: Graph,
                        count: int) -> tuple[int, ...]:
    """Share pointers to old private branches, charging for them in the whole DAG."""
    if not count:
        return ()
    independent = set(puzzle.seeds)
    targets = set(pending)
    for value, (_, left, right) in graph.items():
        if value not in targets and left in independent and right in independent:
            independent.add(value)
    optional = []
    for target in pending:
        if target not in graph:
            continue
        a, b = graph[target][1:]
        for value in (a, b):
            if value in independent and value in graph and value not in ordinary:
                optional.append(value)
    for value in tuple(optional):
        if value in graph:
            for child in graph[value][1:]:
                if child in independent and child in graph and child not in ordinary:
                    optional.append(child)
    return tuple(dict.fromkeys(optional))[:count]


def macro_anchors(puzzle: Puzzle, graph: Graph, pending: list[int], seeds: tuple[int, ...],
                  count: int) -> tuple[tuple[int, ...], Graph]:
    """Choose purchasable short macros near quotient/residue demands."""
    if not count:
        return (), {}
    table = make_table(seeds, puzzle.limit)
    targets = set(pending)
    signal = Counter()
    for target in pending:
        width = target.bit_length()
        scales = sorted(
            (value for value in seeds if 2 <= value <= target // 2),
            key=lambda value: (abs(value.bit_length() - 0.45 * width), value),
        )[:12]
        requests = {isqrt(target)}
        for scale in scales:
            quotient, residue = divmod(target, scale)
            requests.update((quotient, residue, scale - residue, isqrt(quotient)))
        for wanted in requests:
            if wanted <= 4:
                continue
            for step_cost, lower, upper in ((1, table.n0, table.n1),
                                              (2, table.n1, len(table.values))):
                stage = table.values[lower:upper]
                at = int(np.searchsorted(stage, np.uint64(wanted)))
                for local_index in (at - 1, at):
                    if not 0 <= local_index < len(stage):
                        continue
                    index = lower + local_index
                    value = int(table.values[index])
                    if (value in graph or value in targets
                            or abs(value - wanted) * 24 > wanted):
                        continue
                    distance = abs(value - wanted) / wanted
                    signal[index] += 1.0 / (step_cost + 22.0 * distance)
    ordered = sorted(signal, key=lambda index: (-signal[index], int(table.values[index])))
    admitted = []
    macros = {}
    per_band = Counter()
    for index in ordered:
        value = int(table.values[index])
        band = value.bit_length() // 6
        if per_band[band] >= max(2, count // 3):
            continue
        per_band[band] += 1
        admitted.append(value)
        macros.update(decode(seeds, table, (0, index, 0, 0, 0, 0), value))
        if len(admitted) >= count:
            break
    return tuple(admitted), macros


def improve(puzzle: Puzzle, program: Program, gpu: GPUJoin, pivots: int,
            quantity: int, capacity: int, timing: dict[str, float], seven: bool):
    fallback = program
    graph = active_graph(puzzle, first_recipes(puzzle, program))
    candidates = []
    for value in set(puzzle.targets) - set(puzzle.seeds):
        surviving, free = cut(puzzle, graph, value)
        removed = len(graph) - len(surviving)
        if removed >= 5 and len(free) >= 4:
            candidates.append((removed, value, surviving, free))
    for removed, target, surviving, free in sorted(candidates, key=lambda item: (-item[0], item[1]))[:pivots]:
        chosen = anchors_for(puzzle, surviving, free, target, quantity)
        start = perf_counter()
        table = make_table(chosen, puzzle.limit)
        timing["table"] += perf_counter() - start
        timing["values"] += len(table.values)
        rows, clocks = gpu.search(table, target, puzzle.limit, min(7 if seven else 6, removed - 1),
                                  capacity)
        for key, elapsed in clocks.items():
            timing[key] += elapsed
        timing["tested"] += 1
        timing["matches"] += len(rows)
        for candidate in shortest_graphs(puzzle, target, table, chosen, rows, surviving, len(fallback))[:14]:
            alternative = schedule_like(puzzle, fallback, candidate)
            if alternative is None or len(alternative) > len(candidate):
                extra = compile_graph(puzzle, candidate, recompute=True)
                if extra is not None and (alternative is None or len(extra) < len(alternative)):
                    alternative = extra
            if alternative is not None and len(alternative) < len(fallback):
                check(puzzle, alternative)
                fallback = alternative
    return fallback


def improve_affine(puzzle: Puzzle, program: Program, gpu: GPUJoin, pivots: int, quantity: int,
                   capacity: int, timing: dict[str, float], raw_scales: int, radius: int, atoms: int,
                   grows: int, reverse: int, conditional: int, helpers: bool, macros: int,
                   slack: int, audit):
    fallback = program
    graph = active_graph(puzzle, first_recipes(puzzle, program))
    targets = []
    roots = set(graph) if helpers else set(puzzle.targets) - set(puzzle.seeds)
    for value in roots:
        surviving, free = cut(puzzle, graph, value)
        removable = len(graph) - len(surviving)
        if removable >= 6 and len(free) >= 4:
            targets.append((removable, value))
    targets.sort(key=lambda x: (-x[0], int(x[1]).bit_length(), x[1]))
    pending = [value for _, value in targets[:pivots]]
    pool = None
    chosen = ()
    forced = set()
    macro_graph: Graph = {}
    while pending:
        if pool is None:
            surviving, free = cut_many(puzzle, graph, set(pending))
            helpful = tuple(sorted(forced & free.keys()))[:min(8, quantity // 4)]
            kept_quota = max(len(puzzle.seeds) + len(helpful), quantity - macros)
            keep = max(0, min(conditional, kept_quota - len(puzzle.seeds) - len(helpful)))
            paid = conditional_anchors(puzzle, graph, pending, free, keep)
            timing["conditional_literals"] += len(paid)
            helpful += paid
            chosen = anchors_for(puzzle, surviving, free, max(pending), kept_quota, helpful)
            start = perf_counter()
            added, macro_graph = macro_anchors(puzzle, graph, pending, chosen,
                                              min(macros, max(0, quantity - len(chosen))))
            chosen = tuple(sorted((*chosen, *added)))
            timing["macro_literals"] += len(added)
            table = make_table(chosen, puzzle.limit)
            timing["table"] += perf_counter() - start
            timing["values"] += len(table.values)
            pool, clocks = gpu.prepare_pool(table, puzzle.limit)
            for key, elapsed in clocks.items():
                timing[key] += elapsed
            timing["pools"] += 1
        target = pending.pop(0)
        surviving, _ = cut(puzzle, graph, target)
        private = len(graph) - len(surviving)
        budget = min(9, private - 1 + slack)
        if budget < 2:
            continue
        rows, clocks = gpu.query_affine(pool, target, puzzle.limit, budget, capacity, radius,
                                        atoms, raw_scales)
        for key, elapsed in clocks.items():
            timing[key] += elapsed
        timing["tested"] += 1
        timing[f"budget_{budget}"] += 1
        timing[f"private_{private}"] += 1
        timing["raw_hit_cuts"] += int(bool(rows))
        timing["matches"] += len(rows)
        liftings = []
        if conditional:
            short, elapsed = gpu.query_balanced(pool, target, puzzle.limit, min(7, budget), capacity)
            timing["direct"] += elapsed
            timing["direct_hit_cuts"] += int(bool(short))
            timing["direct_matches"] += len(short)
            rows.extend(short)
        if reverse:
            for choice in next_reductions(pool.table, target, puzzle.limit, budget, reverse):
                witnesses, elapsed = gpu.query_balanced(pool, choice.quotient, puzzle.limit,
                                                        budget - choice.overhead, min(24, capacity))
                timing["reverse"] += elapsed
                timing["reverse_queries"] += 1
                timing["reverse_hits"] += int(bool(witnesses))
                for witness in witnesses:
                    smaller = decode(chosen, pool.table, witness, choice.quotient)
                    liftings.append(lift_reduction(pool.table, smaller, choice, target))
        incumbent_length = len(fallback)
        plans = shortest_graphs(puzzle, target, pool.table, chosen, rows, macro_graph | graph,
                                incumbent_length, try_overrides=True, supplemental=liftings,
                                keep_all=audit is not None)
        trial_lengths = []
        for candidate in plans[:12]:
            alternative = schedule_like(puzzle, fallback, candidate)
            if alternative is None or len(alternative) > len(candidate):
                extra = compile_graph(puzzle, candidate, recompute=True)
                if extra is not None and (alternative is None or len(extra) < len(alternative)):
                    alternative = extra
            if alternative is not None:
                check(puzzle, alternative)
                trial_lengths.append(len(alternative))
                if len(alternative) < len(fallback):
                    fallback = alternative
        if audit is not None:
            audit.write(json.dumps({
                "id": puzzle.id,
                "target": target,
                "old_private_cost": private,
                "search_budget": budget,
                "nominal_win_limit": private - 1,
                "old_standalone_dag_size": len(active_graph(puzzle, graph, targets=(target,))),
                "incumbent_program_length": incumbent_length,
                "raw_witnesses": len(rows) + len(liftings),
                "distinct_graphs": len(plans),
                "minimum_graph_length": len(plans[0]) if plans else None,
                "replayed_lengths": trial_lengths,
                "retained_program_length": len(fallback),
            }, separators=(",", ":")) + "\n")
            audit.flush()
        timing["replayed_shorter"] += sum(length < incumbent_length for length in trial_lengths)
        timing["replayed_ties"] += sum(length == incumbent_length for length in trial_lengths)
        timing["replayed_longer"] += sum(length > incumbent_length for length in trial_lengths)
        if len(fallback) < incumbent_length:
            replacement = active_graph(puzzle, first_recipes(puzzle, fallback))
            forced = set(replacement) - set(graph)
            graph = replacement
            timing["winning_cuts"] += 1
            if grows:
                grows -= 1
                pool = None
    return fallback


def smoke(gpu: GPUJoin):
    seeds = (17, 109, 331, 487, 663, 1843, 2837, 12097, 30491, 53573)
    target = ((seeds[0] + seeds[1]) * seeds[2]) ** 2 + (seeds[4] - seeds[3]) * seeds[5]
    table = make_table(seeds, 10**18)
    matches, clocks = gpu.search(table, target, 10**18, 6, 32)
    assert matches, "fused 3-vs-2 kernel missed the known expression"
    puzzle = Puzzle("gpu_smoke", seeds, (target,), 10**18)
    programs = [compile_graph(puzzle, decode(seeds, table, match, target)) for match in matches]
    viable = [program for program in programs if program is not None]
    assert viable
    print(f"GPU smoke test: {target}, table {len(table.values):,}, "
          f"{min(check(puzzle, p) for p in viable)} instructions, {clocks}", flush=True)
    target = ((seeds[0] + seeds[1]) * seeds[2]) ** 2 + ((seeds[3] + seeds[4]) * seeds[5]) ** 2
    seven, clocks = gpu.search(table, target, 10**18, 7, 32)
    witnesses = [row for row in seven if row[0] == 5]
    assert witnesses, "GPU 3-vs-3 kernel missed the known two-square expression"
    puzzle = Puzzle("gpu_seven_smoke", seeds, (target,), 10**18)
    viable = [program for row in witnesses
              if (program := compile_graph(puzzle, decode(seeds, table, row, target))) is not None]
    assert viable
    print(f"GPU 3-vs-3 smoke test: {target}, {len(witnesses)} matches, "
          f"{min(check(puzzle, p) for p in viable)} instructions, {clocks}", flush=True)
    quotient = ((seeds[0] + seeds[1]) * seeds[2]) ** 2
    residual = ((seeds[3] + seeds[4]) * seeds[5]) ** 2
    target = seeds[8] * quotient + residual
    pool, pool_clocks = gpu.prepare_pool(table, 10**18)
    rows, clocks = gpu.query_affine(pool, target, 10**18, 8, 96, 16, 0, len(seeds))
    assert rows, "affine OpenCL search missed a shared two-square expression"
    puzzle = Puzzle("gpu_affine_smoke", seeds, (target,), 10**18)
    programs = [compile_graph(puzzle, decode(seeds, table, row, target)) for row in rows]
    viable = [program for program in programs if program is not None]
    assert viable
    print(f"GPU affine smoke test: {target}, {len(rows)} matches, "
          f"{min(check(puzzle, p) for p in viable)} instructions, {pool_clocks | clocks}", flush=True)
    combined = quotient + residual
    scale = seeds[1]
    offset = seeds[4]
    directed = combined * scale + offset
    transforms = next_reductions(table, directed, 10**18, 9, 200)
    observed = next((choice for choice in transforms if choice.quotient == combined
                     and choice.scale >= 0 and int(table.values[choice.scale]) == scale
                     and choice.residual >= 0 and int(table.values[choice.residual]) == offset), None)
    assert observed is not None, "exact signed reverse projection was not proposed"
    rows, elapsed = gpu.query_balanced(pool, combined, 10**18, 7, 32)
    puzzle = Puzzle("gpu_reverse_smoke", seeds, (directed,), 10**18)
    proofs = [lift_reduction(table, decode(seeds, table, row, combined), observed, directed)
              for row in rows]
    schedules = [program for proof in proofs if (program := compile_graph(puzzle, proof)) is not None]
    assert schedules, "GPU reverse projection had no valid schedule"
    print(f"GPU reverse smoke test: {directed}, "
          f"{min(check(puzzle, p) for p in schedules)} instructions, {elapsed:.6f}s", flush=True)


def controls(puzzles, baseline, gpu, requested, quantity, capacity, output):
    report = Counter()
    timings = Counter()
    best = baseline.copy()
    for puzzle in sorted(puzzles, key=lambda p: (-len(baseline[p.id]), p.id)):
        graph = active_graph(puzzle, first_recipes(puzzle, baseline[puzzle.id]))

        @lru_cache(maxsize=None)
        def small_subtrees(value, budget):
            possibilities = {frozenset()}
            if value in graph and budget > 0:
                _, left, right = graph[value]
                for first in small_subtrees(left, budget - 1):
                    for second in small_subtrees(right, budget - 1):
                        merged = first | second | {value}
                        if len(merged) <= budget:
                            possibilities.add(frozenset(merged))
            return sorted(possibilities, key=lambda shape: (len(shape), sorted(shape)))

        def inputs(shape):
            return {value for out in shape for value in graph[out][1:] if value not in shape}

        used_modes = set()
        for target, root in reversed(tuple(graph.items())):
            if target < 2**35 or root[1] == root[2]:
                continue
            for budget in (6, 7):
                if budget in used_modes or report[f"attempted{budget}"] >= requested:
                    continue
                merged = next((a | b | {target}
                               for a in small_subtrees(root[1], 3) if len(a) == 3
                               for b in small_subtrees(root[2], budget - 4) if len(b) == budget - 4
                               if len(a | b) == budget - 1 and not inputs(a) & b and not inputs(b) & a),
                              None)
                if merged is None:
                    continue
                used_modes.add(budget)
                leaves = inputs(merged)
                fillers = tuple(sorted(set(graph) - merged - leaves))
                chosen = set(puzzle.seeds) | leaves
                for value in fillers[::max(1, len(fillers) // max(1, quantity - len(chosen)))]:
                    if len(chosen) >= quantity:
                        break
                    chosen.add(value)
                seeds = tuple(sorted(chosen))
                table = make_table(seeds, puzzle.limit)
                witness, clocks = gpu.search(table, target, puzzle.limit, budget, capacity)
                timings.update(clocks)
                suffix = str(budget)
                report["attempted" + suffix] += 1
                control = Puzzle(f"{puzzle.id}_control{budget}", seeds, (target,), puzzle.limit)
                matching_root = False
                viable = fused = 0
                best_steps = budget + 1
                for row in witness:
                    recipes = decode(seeds, table, row, target)
                    adopted = compile_graph(control, recipes)
                    if adopted is None:
                        continue
                    viable += 1
                    best_steps = min(best_steps, check(control, adopted))
                    if (budget == 7 and row[0] == 5) or (budget == 6 and 1 <= row[0] <= 4 and row[3]):
                        fused += 1
                    final = recipes.get(target)
                    if final == root or (root[0] in "+*" and final == (root[0], root[2], root[1])):
                        matching_root = True
                report["witness" + suffix] += int(viable > 0)
                report["fused" + suffix] += int(fused > 0)
                report["original_root" + suffix] += matching_root
                score_drop = 0
                if output:
                    original = len(best[puzzle.id])
                    chosen_plans = shortest_graphs(puzzle, target, table, seeds, witness, graph,
                                                   original, try_overrides=True)
                    for complete in chosen_plans[:12]:
                        program = compile_graph(puzzle, complete, recompute=True)
                        if program is not None and len(program) < len(best[puzzle.id]):
                            check(puzzle, program)
                            best[puzzle.id] = program
                    score_drop = original - len(best[puzzle.id])
                    report["real_saved"] += score_drop
                print(f"control {puzzle.id} ({budget}) {target}: {len(table.values):,} atoms, "
                      f"{len(witness)} hits, {fused} fused, same root {matching_root}, "
                      f"validated cost {best_steps if viable else 'none'}, scored delta {score_drop}, "
                      f"{clocks}", flush=True)
            if len(used_modes) == 2:
                break
        if all(report[f"attempted{budget}"] >= requested for budget in (6, 7)):
            break
    if output:
        report["submission"] = write_submission(output, puzzles, best)
    print("controls", dict(report), "device clocks", dict(timings), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path, nargs="?")
    parser.add_argument("baseline", type=Path, nargs="?")
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--controls", type=int, default=0,
                        help="recover real 6- and 7-step expressions with their leaves available")
    parser.add_argument("--seven", action="store_true")
    parser.add_argument("--affine", action="store_true",
                        help="reuse a wide bank for a longer shared affine construction")
    parser.add_argument("--raw-scales", type=int, default=4)
    parser.add_argument("--radius", type=int, default=16)
    parser.add_argument("--scale-atoms", type=int, default=90)
    parser.add_argument("--grows", type=int, default=1)
    parser.add_argument("--reverse", type=int, default=0,
                        help="number of one- or two-step reverse reductions per cut")
    parser.add_argument("--conditional", type=int, default=0,
                        help="number of old private values to keep as optional, paid operands")
    parser.add_argument("--helpers", action="store_true")
    parser.add_argument("--macros", type=int, default=0)
    parser.add_argument("--slack", type=int, default=0,
                        help="search additional nominal instructions for coverage diagnostics")
    parser.add_argument("--audit", type=Path, help="write per-cut diagnostics under the work directory")
    parser.add_argument("--sample", choices=("hard", "even"), default="hard")
    parser.add_argument("--quantity", type=int, default=44)
    parser.add_argument("--pilot", type=int, default=20)
    parser.add_argument("--pivots", type=int, default=2)
    parser.add_argument("--capacity", type=int, default=48)
    parser.add_argument("--directory", type=Path, default=ROOT / "work" / "gpu")
    args = parser.parse_args()
    if (min(args.quantity, args.pivots, args.capacity) < 1
            or min(args.pilot, args.controls, args.raw_scales, args.radius, args.scale_atoms,
                   args.grows, args.reverse, args.conditional, args.macros, args.slack) < 0
            or args.quantity > 64):
        parser.error("invalid search settings")
    gpu = GPUJoin(args.directory)
    print(gpu.device.name, gpu.device.version, flush=True)
    if args.smoke:
        smoke(gpu)
        return
    if args.puzzles is None or args.baseline is None or (args.output is None and not args.controls):
        parser.error("puzzles, baseline, and output paths are required")
    puzzles = read_puzzles(args.puzzles)
    baseline = read_submission(args.baseline)
    total = score(puzzles, baseline)
    if args.controls:
        if args.quantity > 48:
            parser.error("controls use at most 48 anchors")
        controls(puzzles, baseline, gpu, args.controls, args.quantity, args.capacity, args.output)
        return
    best = baseline.copy()
    ordered = sorted(puzzles, key=lambda p: (-len(baseline[p.id]), p.id))
    if args.pilot and args.sample == "even":
        chosen = ordered[::max(1, len(ordered) // args.pilot)][:args.pilot]
    else:
        chosen = ordered if not args.pilot else ordered[:min(args.pilot, len(ordered))]
    timing = Counter()
    start = perf_counter()
    audit = args.audit.open("w", encoding="utf-8") if args.audit else None
    try:
        for at, puzzle in enumerate(chosen, 1):
            if args.affine:
                answer = improve_affine(puzzle, baseline[puzzle.id], gpu, args.pivots, args.quantity,
                                        args.capacity, timing, args.raw_scales, args.radius,
                                        args.scale_atoms, args.grows, args.reverse, args.conditional,
                                        args.helpers, args.macros, args.slack, audit)
            else:
                answer = improve(puzzle, baseline[puzzle.id], gpu, args.pivots, args.quantity,
                                 args.capacity, timing, args.seven)
            delta = len(baseline[puzzle.id]) - len(answer)
            if delta:
                best[puzzle.id] = answer
                total -= delta
            print(f"{at}/{len(chosen)} {puzzle.id} saved {delta}, total {total}, "
                  f"tested {timing['tested']}, {perf_counter() - start:.1f}s", flush=True)
            if at % 5 == 0:
                assert write_submission(args.output, puzzles, best) == total
    finally:
        if audit is not None:
            audit.close()
    assert write_submission(args.output, puzzles, best) == total
    print(dict(timing), flush=True)


if __name__ == "__main__":
    main()

"""
Tests for profiling, logging and code-generation performance.

Run from the `generate` folder:
    python -m unittest discover -s tests -v
or, if pytest is installed (use -s to see the benchmark table):
    pytest tests -s

Time budgets are deliberately generous. On a slow machine scale them with:
    set CODEGEN_PERF_FACTOR=3        (Windows cmd)
    $env:CODEGEN_PERF_FACTOR=3       (PowerShell)
"""

import logging
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import profiling  # noqa: E402
from generator import (
    GenerationConfig,
    build_charset,
    generate_codes,  # noqa: E402
    load_existing_codes,
    random_body,
    save_codes,
)
from profiling import Timer, format_duration, timed  # noqa: E402

PERF_FACTOR = float(os.environ.get("CODEGEN_PERF_FACTOR", "1"))


def best_of(fn, repeats=3):
    """Run fn several times and return the fastest time (reduces noise)."""
    best = float("inf")
    for _ in range(repeats):
        with Timer("best_of", log=False) as t:
            fn()
        best = min(best, t.elapsed)
    return best


# ======================================================================
class TestTimingTools(unittest.TestCase):
    def setUp(self):
        profiling.reset_stats()

    def test_timer_measures_sleep(self):
        with Timer("sleep", log=False) as t:
            time.sleep(0.05)
        self.assertGreaterEqual(t.elapsed, 0.045)
        self.assertLess(t.elapsed, 0.5)

    def test_timer_can_record_stats(self):
        with Timer("recorded", log=False, record_stats=True):
            pass
        self.assertEqual(profiling.get_stats()["recorded"].calls, 1)

    def test_timed_records_calls_total_min_max(self):
        @timed(name="sleeper")
        def sleeper(d):
            time.sleep(d)

        sleeper(0.01)
        sleeper(0.03)
        s = profiling.get_stats()["sleeper"]
        self.assertEqual(s.calls, 2)
        self.assertGreaterEqual(s.total, 0.035)
        self.assertLessEqual(s.minimum, s.maximum)
        self.assertAlmostEqual(s.average, s.total / 2)

    def test_timed_preserves_name_and_return_value(self):
        @timed
        def add(a, b):
            """adds"""
            return a + b

        self.assertEqual(add(2, 3), 5)
        self.assertEqual(add.__name__, "add")
        self.assertEqual(add.__doc__, "adds")

    def test_timed_records_even_when_function_raises(self):
        @timed(name="boom")
        def boom():
            raise RuntimeError("x")

        with self.assertRaises(RuntimeError):
            boom()
        self.assertEqual(profiling.get_stats()["boom"].calls, 1)

    def test_format_duration(self):
        self.assertEqual(format_duration(0.0005), "500 µs")
        self.assertTrue(format_duration(0.0005).endswith("µs"))
        self.assertTrue(format_duration(0.25).endswith("ms"))
        self.assertTrue(format_duration(2.5).endswith(" s"))
        self.assertIn("min", format_duration(125))

    def test_report_lists_recorded_functions(self):
        @timed(name="reported_fn")
        def f():
            pass

        f()
        self.assertIn("reported_fn", profiling.format_report())


# ======================================================================
class TestLogging(unittest.TestCase):
    def setUp(self):
        profiling.reset_stats()
        self.tmp = tempfile.TemporaryDirectory()
        self.log_file = Path(self.tmp.name) / "logs" / "test.log"
        profiling.setup_logging(
            enabled=True, log_file=self.log_file, level=logging.DEBUG
        )

    def tearDown(self):
        profiling.shutdown_logging()
        profiling.set_logging_enabled(True)
        self.tmp.cleanup()

    def _flush(self):
        for h in profiling.logger.handlers:
            h.flush()

    def test_log_file_is_created_and_contains_timing(self):
        @timed(name="logged_fn")
        def f():
            pass

        f()
        self._flush()
        content = self.log_file.read_text(encoding="utf-8")
        self.assertIn("logged_fn took", content)

    def test_generate_codes_is_logged(self):
        generate_codes(GenerationConfig(count=10, length=8))
        self._flush()
        content = self.log_file.read_text(encoding="utf-8")
        self.assertIn("generate_codes took", content)
        self.assertIn("Generating 10 codes", content)

    def test_disabling_logging_stops_output(self):
        profiling.logger.info("before-disable")
        profiling.set_logging_enabled(False)
        profiling.logger.info("while-disabled")
        profiling.set_logging_enabled(True)
        profiling.logger.info("after-enable")
        self._flush()
        content = self.log_file.read_text(encoding="utf-8")
        self.assertIn("before-disable", content)
        self.assertNotIn("while-disabled", content)
        self.assertIn("after-enable", content)

    def test_stats_still_recorded_when_logging_disabled(self):
        profiling.set_logging_enabled(False)
        generate_codes(GenerationConfig(count=5, length=6))
        self.assertTrue(
            any(k.endswith("generate_codes") for k in profiling.get_stats())
        )


# ======================================================================
class TestGenerationCorrectness(unittest.TestCase):
    def test_codes_are_unique_and_correct_count(self):
        r = generate_codes(GenerationConfig(count=5000, length=10))
        self.assertEqual(len(r.codes), 5000)
        self.assertEqual(len(set(r.codes)), 5000)

    def test_numbers_only(self):
        r = generate_codes(
            GenerationConfig(
                count=200,
                length=8,
                use_upper=False,
                exclude_ambiguous=False,
                separator="",
            )
        )
        self.assertTrue(all(c.isdigit() and len(c) == 8 for c in r.codes))

    def test_prefix_suffix_and_grouping(self):
        r = generate_codes(
            GenerationConfig(
                count=20, length=8, group_size=4, prefix="PRE", suffix="SUF"
            )
        )
        for c in r.codes:
            parts = c.split("-")
            self.assertEqual(parts[0], "PRE")
            self.assertEqual(parts[-1], "SUF")
            self.assertEqual([len(p) for p in parts[1:-1]], [4, 4])

    def test_existing_codes_are_skipped(self):
        first = generate_codes(
            GenerationConfig(count=50, length=6, use_upper=False)
        ).codes
        second = generate_codes(
            GenerationConfig(count=50, length=6, use_upper=False), existing=set(first)
        ).codes
        self.assertTrue(set(first).isdisjoint(second))

    def test_impossible_request_raises(self):
        with self.assertRaises(ValueError):
            generate_codes(
                GenerationConfig(
                    count=1000, length=2, use_upper=False, exclude_ambiguous=False
                )
            )

    def test_empty_pool_raises(self):
        with self.assertRaises(ValueError):
            generate_codes(GenerationConfig(use_digits=False, use_upper=False))

    def test_no_repeats(self):
        body = random_body("AB", 200, no_repeats=True)
        self.assertTrue(all(a != b for a, b in zip(body, body[1:])))


# ======================================================================
class TestPerformance(unittest.TestCase):
    """Execution-time budgets. Failing here means a performance regression."""

    BUDGETS = [  # (count, length, max seconds)
        (1_000, 12, 1.0),
        (10_000, 12, 5.0),
        (50_000, 16, 20.0),
    ]

    def setUp(self):
        profiling.set_logging_enabled(
            False
        )  # keep logging overhead out of measurements
        profiling.reset_stats()

    def tearDown(self):
        profiling.set_logging_enabled(True)

    def test_generation_within_time_budget(self):
        for count, length, budget in self.BUDGETS:
            with self.subTest(count=count, length=length):
                cfg = GenerationConfig(
                    count=count, length=length, use_lower=True, group_size=4
                )
                elapsed = best_of(lambda: generate_codes(cfg), repeats=2)
                self.assertLess(
                    elapsed,
                    budget * PERF_FACTOR,
                    f"{count:,} codes took {format_duration(elapsed)} "
                    f"(budget {budget * PERF_FACTOR}s)",
                )

    def test_generation_scales_roughly_linearly(self):
        small = best_of(
            lambda: generate_codes(GenerationConfig(count=5_000, length=12))
        )
        large = best_of(
            lambda: generate_codes(GenerationConfig(count=20_000, length=12))
        )
        # 4x the work should cost well under 10x the time
        self.assertLess(large, small * 10, f"small={small:.3f}s large={large:.3f}s")

    def test_no_repeats_overhead_is_bounded(self):
        base = best_of(
            lambda: generate_codes(GenerationConfig(count=10_000, length=12))
        )
        nr = best_of(
            lambda: generate_codes(
                GenerationConfig(count=10_000, length=12, no_repeats=True)
            )
        )
        self.assertLess(nr, base * 5 + 0.5)

    def test_charset_build_is_fast(self):
        cfg = GenerationConfig(use_lower=True, use_symbols=True, custom_chars="äöü")
        elapsed = best_of(lambda: [build_charset(cfg) for _ in range(1_000)])
        self.assertLess(elapsed, 1.0 * PERF_FACTOR)

    def test_save_and_load_are_fast(self):
        codes = generate_codes(GenerationConfig(count=20_000, length=12)).codes
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "codes.txt"
            t_save = best_of(lambda: save_codes(path, codes))
            t_load = best_of(lambda: load_existing_codes(path))
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 20_000)
            self.assertEqual(len(load_existing_codes(path)), 20_000)
        self.assertLess(t_save, 2.0 * PERF_FACTOR)
        self.assertLess(t_load, 2.0 * PERF_FACTOR)

    def test_decorator_overhead_is_small(self):
        def plain():
            return 1

        decorated = timed(plain)
        n = 20_000
        t_plain = best_of(lambda: [plain() for _ in range(n)])
        t_deco = best_of(lambda: [decorated() for _ in range(n)])
        per_call_us = (t_deco - t_plain) / n * 1_000_000
        self.assertLess(
            per_call_us, 100, f"decorator adds {per_call_us:.1f} µs per call"
        )


# ======================================================================
class TestBenchmarkReport(unittest.TestCase):
    """Prints a benchmark table (visible with `-v` / `pytest -s`). Always passes if codes are generated."""

    def test_print_benchmark_table(self):
        profiling.set_logging_enabled(False)
        try:
            rows = []
            for count in (100, 1_000, 10_000, 100_000):
                cfg = GenerationConfig(count=count, length=12, group_size=4)
                t = best_of(lambda: generate_codes(cfg), repeats=2)
                rows.append((count, t))
                self.assertGreater(t, 0)
            print("\n\n  Benchmark: generate_codes (length 12, group 4)")
            print("  " + "-" * 52)
            print(f"  {'Codes':>10}  {'Time':>12}  {'Codes/sec':>14}")
            for count, t in rows:
                print(f"  {count:>10,}  {format_duration(t):>12}  {count / t:>14,.0f}")
            print()
        finally:
            profiling.set_logging_enabled(True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

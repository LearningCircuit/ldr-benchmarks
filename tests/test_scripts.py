"""
Unit tests for scripts/build_leaderboards.py and scripts/validate_yamls.py.

Uses the stdlib `unittest` framework so the tests run with just Python
and pyyaml installed, with no additional dev dependencies:

    python -m unittest tests/test_scripts.py

The tests create temporary results/ trees with synthetic YAML files,
run the aggregator and validator directly, and assert on the output
CSVs, error lists, and return codes. No network access. A real git
repository is only created for the git-contributor inference tests,
and only when git is available on PATH.
"""

from __future__ import annotations

import csv
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load(module_name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, SCRIPTS_DIR / file_name
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


build_leaderboards = _load("build_leaderboards", "build_leaderboards.py")
validate_yamls = _load("validate_yamls", "validate_yamls.py")


# -------------------------------------------------------------------
# Fixture strings
# -------------------------------------------------------------------

SIMPLEQA_SOURCE_BASED = dedent("""
    model: qwen3.5:9b
    model_provider: OLLAMA
    search_engine: serper
    results:
      dataset: SimpleQA
      total_questions: 200
      source_based:
        accuracy: "91.2% (182/200)"
        iterations: 10
        questions_per_iteration: 1
        avg_time_per_question: "1m 18s"
    configuration:
      temperature: 0.7
      context_window: 36352
      max_tokens: 30000
    evaluator:
      model: qwen3.5:9b
      provider: ollama
      temperature: 0
    versions:
      ldr_version: 1.5.6
    date_tested: 2026-04-06
""").strip() + "\n"

SIMPLEQA_FOCUSED_ITERATION = dedent("""
    model: llama3.1:70b
    model_provider: OLLAMA
    quantization: Q4_K_M
    search_engine: searxng
    hardware:
      gpu: RTX 4090 24GB
      ram: 64GB DDR5
      cpu: AMD Ryzen 9 7950X
    results:
      dataset: SimpleQA
      total_questions: 100
      focused_iteration:
        accuracy: "87% (87/100)"
        iterations: 8
        questions_per_iteration: 5
        avg_time_per_question: "95s"
    configuration:
      context_window: 32768
      temperature: 0.1
      max_tokens: 4096
    evaluator:
      model: anthropic/claude-3.7-sonnet
      provider: openai_endpoint
      temperature: 0
    versions:
      ldr_version: 1.5.6
    date_tested: 2026-03-15
""").strip() + "\n"

BROWSECOMP_LANGGRAPH = dedent("""
    model: gpt-4o
    model_provider: openai
    search_engine: tavily
    results:
      dataset: browsecomp
      total_questions: 50
      langgraph_agent:
        accuracy: "44% (22/50)"
        iterations: 15
        questions_per_iteration: 1
        avg_time_per_question: "3m 12s"
    configuration:
      temperature: 0.3
      context_window: 128000
    evaluator:
      model: anthropic/claude-3.7-sonnet
      provider: openai_endpoint
      temperature: 0
    versions:
      ldr_version: 1.5.6
    date_tested: 2026-02-10
""").strip() + "\n"

XBENCH_RESTRICTED_OK = dedent("""
    model: gpt-4o
    model_provider: openai
    search_engine: serper
    results:
      dataset: xbench_deepsearch
      total_questions: 30
      source_based:
        accuracy: "60% (18/30)"
        iterations: 5
        questions_per_iteration: 2
        avg_time_per_question: "2m"
    configuration:
      temperature: 0.2
    evaluator:
      model: anthropic/claude-3.7-sonnet
      provider: openai_endpoint
      temperature: 0
    versions:
      ldr_version: 1.5.6
    date_tested: 2026-03-20
""").strip() + "\n"


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def _write(tmp_path: Path, rel: str, content: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _make_valid_fixture(tmp_path: Path) -> Path:
    _write(tmp_path, "results/simpleqa/source-based/serper/qwen3.5-9b_2026-04-06.yaml",
           SIMPLEQA_SOURCE_BASED)
    _write(tmp_path, "results/simpleqa/focused-iteration/searxng/llama3.1-70b_2026-03-15.yaml",
           SIMPLEQA_FOCUSED_ITERATION)
    _write(tmp_path, "results/browsecomp/langgraph-agent/tavily/gpt-4o_2026-02-10.yaml",
           BROWSECOMP_LANGGRAPH)
    return tmp_path / "results"


def _run_build(tmp_path: Path) -> Path:
    """Run build_leaderboards.main() in tmp_path and return the leaderboards dir."""
    out_dir = tmp_path / "leaderboards"
    cwd_before = Path.cwd()
    argv_before = sys.argv[:]
    try:
        import os
        os.chdir(tmp_path)
        sys.argv = [
            "build_leaderboards.py",
            "--results-dir", "results",
            "--out-dir", str(out_dir),
        ]
        rc = build_leaderboards.main()
        assert rc == 0, f"build_leaderboards exited with {rc}"
    finally:
        os.chdir(cwd_before)
        sys.argv = argv_before
    return out_dir


def _run_validate(tmp_path: Path) -> int:
    cwd_before = Path.cwd()
    argv_before = sys.argv[:]
    try:
        import os
        os.chdir(tmp_path)
        sys.argv = ["validate_yamls.py", "--results-dir", "results"]
        return validate_yamls.main()
    finally:
        os.chdir(cwd_before)
        sys.argv = argv_before


class TmpDirTestCase(unittest.TestCase):
    """Provides self.tmp_path per test, cleaned up automatically."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="ldr-bench-test-")
        self.tmp_path = Path(self._tmpdir)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)


# -------------------------------------------------------------------
# build_leaderboards tests
# -------------------------------------------------------------------


class TestAccuracyParsing(unittest.TestCase):
    def test_full_form(self):
        self.assertEqual(build_leaderboards.parse_accuracy("91.2% (182/200)"),
                         (91.2, 182, 200))

    def test_integer_percent(self):
        self.assertEqual(build_leaderboards.parse_accuracy("87% (87/100)"),
                         (87.0, 87, 100))

    def test_percent_only(self):
        self.assertEqual(build_leaderboards.parse_accuracy("50 %"),
                         (50.0, None, None))

    def test_fraction_only(self):
        self.assertEqual(build_leaderboards.parse_accuracy("(5/10)"),
                         (50.0, 5, 10))

    def test_unparseable(self):
        self.assertEqual(build_leaderboards.parse_accuracy("nonsense"),
                         (None, None, None))

    def test_none(self):
        self.assertEqual(build_leaderboards.parse_accuracy(None),
                         (None, None, None))


class TestBenchmarkSlugLookup(unittest.TestCase):
    def test_known_simpleqa(self):
        self.assertEqual(build_leaderboards.lookup_benchmark_slug("SimpleQA"), "simpleqa")

    def test_known_browsecomp(self):
        self.assertEqual(build_leaderboards.lookup_benchmark_slug("BrowseComp"), "browsecomp")

    def test_xbench_underscore(self):
        self.assertEqual(
            build_leaderboards.lookup_benchmark_slug("xbench_deepsearch"),
            "xbench-deepsearch")

    def test_xbench_hyphen(self):
        self.assertEqual(
            build_leaderboards.lookup_benchmark_slug("xbench-deepsearch"),
            "xbench-deepsearch")

    def test_unknown_fallback(self):
        self.assertEqual(
            build_leaderboards.lookup_benchmark_slug("Some New Bench"),
            "some-new-bench")


class TestBuildLeaderboardsEndToEnd(TmpDirTestCase):
    def test_produces_expected_csvs(self):
        _make_valid_fixture(self.tmp_path)
        out_dir = _run_build(self.tmp_path)
        self.assertTrue((out_dir / "all.csv").exists())
        self.assertTrue((out_dir / "simpleqa.csv").exists())
        self.assertTrue((out_dir / "browsecomp.csv").exists())

        self.assertEqual(len(_read_csv(out_dir / "all.csv")), 3)
        self.assertEqual(len(_read_csv(out_dir / "simpleqa.csv")), 2)
        self.assertEqual(len(_read_csv(out_dir / "browsecomp.csv")), 1)

    def test_strategy_detection_is_not_hardcoded(self):
        """Aggregator must honour the actual strategy key in the YAML,
        including strategies beyond focused_iteration/source_based
        (this is the bug the benchmark_results.html exporter had)."""
        _make_valid_fixture(self.tmp_path)
        out_dir = _run_build(self.tmp_path)
        browsecomp_rows = _read_csv(out_dir / "browsecomp.csv")
        self.assertEqual(len(browsecomp_rows), 1)
        self.assertEqual(browsecomp_rows[0]["strategy"], "langgraph_agent")

    def test_row_fields_are_populated(self):
        _make_valid_fixture(self.tmp_path)
        out_dir = _run_build(self.tmp_path)
        rows = _read_csv(out_dir / "all.csv")
        by_model = {r["model"]: r for r in rows}

        qwen = by_model["qwen3.5:9b"]
        self.assertEqual(qwen["dataset"], "SimpleQA")
        self.assertEqual(qwen["strategy"], "source_based")
        self.assertEqual(qwen["search_engine"], "serper")
        self.assertEqual(float(qwen["accuracy_pct"]), 91.2)
        self.assertEqual(qwen["correct"], "182")
        self.assertEqual(qwen["total"], "200")
        self.assertEqual(qwen["iterations"], "10")
        self.assertEqual(qwen["ldr_version"], "1.5.6")
        self.assertEqual(qwen["date_tested"], "2026-04-06")

        llama = by_model["llama3.1:70b"]
        self.assertEqual(llama["quantization"], "Q4_K_M")
        self.assertEqual(llama["hardware_gpu"], "RTX 4090 24GB")
        self.assertEqual(llama["hardware_ram"], "64GB DDR5")
        self.assertEqual(llama["hardware_cpu"], "AMD Ryzen 9 7950X")
        self.assertEqual(llama["evaluator_model"], "anthropic/claude-3.7-sonnet")

    def test_all_csv_sorted_by_accuracy_desc(self):
        _make_valid_fixture(self.tmp_path)
        out_dir = _run_build(self.tmp_path)
        rows = _read_csv(out_dir / "all.csv")
        pcts = [float(r["accuracy_pct"]) for r in rows]
        self.assertEqual(pcts, sorted(pcts, reverse=True))

    def test_empty_results_dir(self):
        (self.tmp_path / "results").mkdir()
        out_dir = _run_build(self.tmp_path)
        self.assertTrue((out_dir / "all.csv").exists())
        self.assertEqual(_read_csv(out_dir / "all.csv"), [])

    def test_multiple_strategies_in_one_yaml(self):
        content = dedent("""
            model: test-model
            model_provider: OLLAMA
            search_engine: serper
            results:
              dataset: SimpleQA
              total_questions: 50
              focused_iteration:
                accuracy: "80% (40/50)"
                iterations: 8
                questions_per_iteration: 5
                avg_time_per_question: "90s"
              source_based:
                accuracy: "70% (35/50)"
                iterations: 5
                questions_per_iteration: 3
                avg_time_per_question: "60s"
            configuration:
              temperature: 0.1
            evaluator:
              model: test-grader
            versions:
              ldr_version: 1.5.6
            date_tested: 2026-04-01
        """).strip() + "\n"
        _write(self.tmp_path,
               "results/simpleqa/source-based/serper/test_2026-04-01.yaml",
               content)
        out_dir = _run_build(self.tmp_path)
        rows = _read_csv(out_dir / "simpleqa.csv")
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(r["strategy"] for r in rows),
                         ["focused_iteration", "source_based"])


# -------------------------------------------------------------------
# Contributor inference (git-backed) tests
# -------------------------------------------------------------------


HAS_GIT = shutil.which("git") is not None


@unittest.skipUnless(HAS_GIT, "git not available on PATH")
class TestContributorInference(TmpDirTestCase):
    def _init_git_repo(self):
        subprocess.run(["git", "init", "-q"], cwd=self.tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "alice@example.com"],
                       cwd=self.tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "Alice Contributor"],
                       cwd=self.tmp_path, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"],
                       cwd=self.tmp_path, check=True)

    def _commit_all(self, message: str):
        subprocess.run(["git", "add", "-A"], cwd=self.tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", message],
                       cwd=self.tmp_path, check=True)

    def test_infers_contributor_from_git_when_yaml_missing(self):
        self._init_git_repo()
        _write(self.tmp_path,
               "results/simpleqa/source-based/serper/q_2026-04-06.yaml",
               SIMPLEQA_SOURCE_BASED)
        self._commit_all("add alice result")

        out_dir = _run_build(self.tmp_path)
        rows = _read_csv(out_dir / "simpleqa.csv")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["contributor"], "Alice Contributor")
        self.assertEqual(rows[0]["contributor_source"], "git")

    def test_explicit_yaml_contributor_wins(self):
        self._init_git_repo()
        with_handle = SIMPLEQA_SOURCE_BASED + "contributor: explicit-handle\n"
        _write(self.tmp_path,
               "results/simpleqa/source-based/serper/q_2026-04-06.yaml",
               with_handle)
        self._commit_all("add explicit-handle result")

        out_dir = _run_build(self.tmp_path)
        rows = _read_csv(out_dir / "simpleqa.csv")
        self.assertEqual(rows[0]["contributor"], "explicit-handle")
        self.assertEqual(rows[0]["contributor_source"], "yaml")

    def test_git_unavailable_leaves_contributor_empty(self):
        """Outside a git repo the fallback quietly returns ''."""
        # tmp_path is not a git repo
        _write(self.tmp_path,
               "results/simpleqa/source-based/serper/q_2026-04-06.yaml",
               SIMPLEQA_SOURCE_BASED)
        out_dir = _run_build(self.tmp_path)
        rows = _read_csv(out_dir / "simpleqa.csv")
        self.assertEqual(rows[0]["contributor"], "")
        self.assertEqual(rows[0]["contributor_source"], "")

    def test_later_edit_does_not_steal_authorship(self):
        self._init_git_repo()
        _write(self.tmp_path,
               "results/simpleqa/source-based/serper/q_2026-04-06.yaml",
               SIMPLEQA_SOURCE_BASED)
        self._commit_all("add alice result")

        # Another user edits the file later.
        subprocess.run(["git", "config", "user.email", "bob@example.com"],
                       cwd=self.tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "Bob Editor"],
                       cwd=self.tmp_path, check=True)
        edited = SIMPLEQA_SOURCE_BASED.replace("91.2", "91.3")
        _write(self.tmp_path,
               "results/simpleqa/source-based/serper/q_2026-04-06.yaml",
               edited)
        self._commit_all("fix typo in alice's file")

        out_dir = _run_build(self.tmp_path)
        rows = _read_csv(out_dir / "simpleqa.csv")
        self.assertEqual(rows[0]["contributor"], "Alice Contributor",
                         "Later editor must not steal original contributor credit")
        self.assertEqual(rows[0]["contributor_source"], "git")


# -------------------------------------------------------------------
# validate_yamls tests
# -------------------------------------------------------------------


class TestValidateYamls(TmpDirTestCase):
    def test_valid_fixture_passes(self):
        _make_valid_fixture(self.tmp_path)
        self.assertEqual(_run_validate(self.tmp_path), 0)

    def test_examples_rejected_for_browsecomp(self):
        bad = dedent("""
            model: test
            model_provider: test
            search_engine: serper
            results:
              dataset: browsecomp
              total_questions: 10
              source_based:
                accuracy: "50% (5/10)"
            examples:
              - question: "leaked browsecomp question"
                correct_answer: "x"
                model_answer: "x"
                result: correct
        """).strip() + "\n"
        path = _write(self.tmp_path,
                      "results/browsecomp/source-based/serper/bad.yaml", bad)
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertTrue(any("restricted" in e and "examples" in e.lower() for e in errs),
                        f"expected restricted-examples error, got: {errs}")

    def test_examples_rejected_for_xbench(self):
        bad = dedent("""
            model: test
            model_provider: test
            search_engine: serper
            results:
              dataset: xbench_deepsearch
              total_questions: 10
              source_based:
                accuracy: "50% (5/10)"
            examples:
              - question: "leaked xbench question"
                correct_answer: "x"
                model_answer: "x"
                result: correct
        """).strip() + "\n"
        path = _write(self.tmp_path,
                      "results/xbench-deepsearch/source-based/serper/bad.yaml", bad)
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertTrue(any("restricted" in e and "examples" in e.lower() for e in errs))

    def test_examples_allowed_for_simpleqa(self):
        good = SIMPLEQA_SOURCE_BASED + dedent("""
            examples:
              - question: "What is 2+2?"
                correct_answer: "4"
                model_answer: "4"
                result: correct
                dataset: simpleqa
                processing_time_seconds: 1.0
        """).strip() + "\n"
        path = _write(self.tmp_path,
                      "results/simpleqa/source-based/serper/ok.yaml", good)
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertEqual(errs, [])

    def test_sensitive_api_key_detected(self):
        bad = SIMPLEQA_SOURCE_BASED + \
            'notes: "API key: sk-abcdefghijklmnopqrstuvwxyz1234567890"\n'
        path = _write(self.tmp_path,
                      "results/simpleqa/source-based/serper/leak.yaml", bad)
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertTrue(any("API key" in e for e in errs))

    def test_hf_token_detected(self):
        bad = SIMPLEQA_SOURCE_BASED + \
            'notes: "token hf_abcdefghijklmnopqrstuvwxyz1234"\n'
        path = _write(self.tmp_path,
                      "results/simpleqa/source-based/serper/leak.yaml", bad)
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertTrue(any("Hugging Face token" in e for e in errs))

    def test_unknown_dataset_rejected(self):
        bad = dedent("""
            model: test
            model_provider: test
            search_engine: serper
            results:
              dataset: SuperBench9000
              total_questions: 10
              source_based:
                accuracy: "50% (5/10)"
        """).strip() + "\n"
        path = _write(self.tmp_path,
                      "results/superbench9000/source-based/serper/bad.yaml", bad)
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertTrue(any("whitelist" in e.lower() for e in errs))

    def test_wrong_path_dataset_rejected(self):
        path = _write(self.tmp_path,
                      "results/browsecomp/source-based/serper/wrong.yaml",
                      SIMPLEQA_SOURCE_BASED)
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertTrue(any("path dataset" in e for e in errs))

    def test_wrong_path_strategy_rejected(self):
        path = _write(self.tmp_path,
                      "results/simpleqa/focused-iteration/serper/wrong.yaml",
                      SIMPLEQA_SOURCE_BASED)
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertTrue(any("path strategy" in e for e in errs))

    def test_wrong_path_search_engine_rejected(self):
        path = _write(self.tmp_path,
                      "results/simpleqa/source-based/searxng/wrong.yaml",
                      SIMPLEQA_SOURCE_BASED)
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertTrue(any("path search_engine" in e for e in errs))

    def test_missing_required_top_level(self):
        bad = dedent("""
            model: test
            results:
              dataset: SimpleQA
              total_questions: 10
              source_based:
                accuracy: "50% (5/10)"
        """).strip() + "\n"
        path = _write(self.tmp_path,
                      "results/simpleqa/source-based/serper/missing.yaml", bad)
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertTrue(any("missing required top-level key: model_provider" in e for e in errs))
        self.assertTrue(any("missing required top-level key: search_engine" in e for e in errs))

    def test_invalid_yaml_rejected(self):
        path = _write(self.tmp_path,
                      "results/simpleqa/source-based/serper/broken.yaml",
                      "this: is: not: valid: yaml: [\n")
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertTrue(any("invalid YAML" in e for e in errs))

    def test_missing_accuracy_rejected(self):
        bad = dedent("""
            model: test
            model_provider: test
            search_engine: serper
            results:
              dataset: SimpleQA
              total_questions: 10
              source_based:
                iterations: 5
        """).strip() + "\n"
        path = _write(self.tmp_path,
                      "results/simpleqa/source-based/serper/noacc.yaml", bad)
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertTrue(any("accuracy is missing" in e for e in errs))

    def test_xbench_restricted_without_examples_passes(self):
        path = _write(self.tmp_path,
                      "results/xbench-deepsearch/source-based/serper/ok.yaml",
                      XBENCH_RESTRICTED_OK)
        errs = validate_yamls.check_file(path, self.tmp_path / "results")
        self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()

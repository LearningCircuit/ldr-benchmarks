# Local Deep Research — Community Benchmarks

Community-submitted benchmark results for
[Local Deep Research (LDR)](https://github.com/LearningCircuit/local-deep-research)
on SimpleQA, BrowseComp, and xbench-DeepSearch.

This repository is the **source of truth** for raw YAML submissions,
PR review, CI validation, and leaderboard regeneration. Aggregated
leaderboard CSVs are synced automatically to a companion Hugging Face
dataset for browsing and discovery:

👉 **[huggingface.co/datasets/local-deep-research/ldr-benchmarks](https://huggingface.co/datasets/local-deep-research/ldr-benchmarks)**

## Quick contribution path

1. Run your benchmark from the LDR web UI at `/benchmark` (LDR v0.6.0+)
2. On the *Benchmark Results* page, click the **YAML** button next to
   your completed run — this downloads a pre-filled file
3. Review the file:
   - Fill in any blank hardware / version fields you know
   - For **BrowseComp** or **xbench** runs, strip any `examples:` block
     (required — these benchmarks prohibit plain-text question/answer
     sharing; see *Benchmark sharing policy* below)
4. Open a Pull Request adding the file at:
   ```
   results/{dataset}/{strategy}/{search_engine}/{model}_{YYYY-MM-DD}.yaml
   ```
   - `{dataset}` — `simpleqa`, `browsecomp`, `xbench-deepsearch`
   - `{strategy}` — e.g. `focused-iteration`, `source-based`,
     `langgraph-agent`, or any other LDR strategy (hyphenated form)
   - `{search_engine}` — e.g. `searxng`, `serper`, `tavily`
5. CI runs automatically on your PR, validating the schema and flagging
   any issues. A maintainer merges once checks pass.

After merge, GitHub Actions regenerates `leaderboards/*.csv` and
pushes them to the Hugging Face dataset.

## Repository layout

```
results/                        # raw YAML submissions (source of truth)
  simpleqa/
    {strategy}/
      {search_engine}/
        {model}_{date}.yaml
  browsecomp/
    ...
  xbench-deepsearch/
    ...

leaderboards/                   # auto-generated, do not edit by hand
  all.csv
  simpleqa.csv
  browsecomp.csv
  xbench-deepsearch.csv

scripts/
  validate_yamls.py             # schema + policy validator (CI)
  build_leaderboards.py         # YAML → CSV aggregator (CI)
  sync_to_hf.py                 # pushes CSVs + HF README to HF (CI)

.github/workflows/
  validate.yml                  # runs on every PR
  publish.yml                   # runs on merge to main

hf_README.md                    # README shown on the Hugging Face dataset
README.md                       # this file
```

## Result file schema

The schema follows LDR's official `benchmark_template.yaml`. The
easiest way to produce a well-formed file is to use the built-in
exporter in the LDR web UI, which generates this format automatically.

```yaml
# Model Information
model: qwen3.5:9b
model_provider: OLLAMA
quantization:                    # optional, e.g. Q4_K_M

# Search Engine
search_engine: serper
search_provider_version:
average_results_per_query:

# Hardware
hardware:
  gpu:
  ram:
  cpu:

# Benchmark Results
results:
  dataset: SimpleQA              # simpleqa | browsecomp | xbench_deepsearch
  total_questions: 200

  source_based:                  # any LDR strategy key; include as many
    accuracy: "91.2% (182/200)"  # as were actually run
    iterations: 10
    questions_per_iteration: 1
    avg_time_per_question: "1m 18s"
    total_tokens_used:

# Configuration
configuration:
  context_window: 36352
  temperature: 0.7
  max_tokens: 30000
  local_provider_context_window_size: 36352

# Evaluator / Grader
evaluator:
  model: anthropic/claude-3.7-sonnet
  provider: openai_endpoint
  endpoint_url: https://openrouter.ai/api/v1
  temperature: 0

# Versions
versions:
  ldr_version: 1.5.6
  ollama_version:
  searxng_version:

# Test Details
test_details:
  date_tested: 2026-04-06
  rate_limiting_issues:
  search_failures:

# Notes
notes: |
  Any observations about this run.

# Individual examples (optional, SimpleQA only)
# examples:
#   - question: "..."
#     correct_answer: "..."
#     model_answer: "..."
#     result: correct            # correct | incorrect
#     dataset: simpleqa
#     processing_time_seconds: 45.3
```

Strategy keys under `results:` are taken from LDR's internal strategy
names (e.g. `source_based`, `focused_iteration`, `langgraph_agent`,
`evidence_based`, etc.). Use whichever strategies you actually ran.
The path uses the hyphenated form (`source-based/`, `focused-iteration/`).

## Supported benchmarks & sharing policy

| Benchmark | Canonical ID | Path slug | Examples allowed? |
|---|---|---|---|
| SimpleQA | `simpleqa` | `simpleqa` | ✅ Yes |
| BrowseComp | `browsecomp` | `browsecomp` | ❌ No (encrypted, canary-protected) |
| xbench-DeepSearch | `xbench_deepsearch` | `xbench-deepsearch` | ❌ No (encrypted) |

- **SimpleQA** is MIT-licensed and openly distributed. Full per-question
  examples are welcome in submissions.
- **BrowseComp** is distributed encrypted with a canary string. OpenAI
  explicitly states that benchmark data should never appear as plain
  text online. CI will reject any BrowseComp submission containing
  an `examples:` block.
- **xbench-DeepSearch** is also distributed encrypted. The xbench team
  asks that plain-text questions/answers not be uploaded online. CI
  will reject any xbench submission containing an `examples:` block.

> ⚠️ **If you are not sure whether it is safe to share the examples —
> do not upload them.** Summary-only submissions (no `examples:` block)
> are the default and preferred format for every benchmark. You lose
> nothing in the leaderboards by omitting examples.

### Adding a new benchmark

When LDR adds support for a new benchmark dataset, update the
`BENCHMARKS` whitelist in **both**:

- `scripts/validate_yamls.py`
- `scripts/build_leaderboards.py`

Keep the `canonical_id` in sync with LDR's
`src/local_deep_research/benchmarks/datasets/__init__.py` registry.

## Considerations for using the data

This is a community-submitted leaderboard, not a controlled experiment.

- **Self-reported.** CI validates schema but not that a run actually
  happened as described.
- **Evaluator bias.** Most submissions use an LLM grader (Claude 3.7
  Sonnet by default). Expect ~1% grading error.
- **Small sample sizes.** Typical runs use 50–200 questions. Confidence
  intervals are wide; small differences are usually not significant.
- **Timing is environment-dependent.** Compare `avg_time_per_question`
  with caution across different hardware/network setups.
- **Contamination risk.** SimpleQA is publicly distributed. BrowseComp
  and xbench mitigate this with encryption.
- **Strategy semantics drift** between LDR versions — prefer comparing
  runs tagged with the same `ldr_version`.

## Contributor attribution

Each CSV row includes a `contributor` column and a `contributor_source`
column indicating where the name came from:

- **`yaml`** — the submitter set an explicit `contributor:` field in the
  YAML. This wins over everything else.
- **`git`** — no explicit field; the aggregator ran
  `git log --follow --diff-filter=A` on the result file and used the
  author of the commit that first added it. Later edits to the file
  do not overwrite the original contributor.
- **`""`** (empty) — neither a YAML field nor a git history was
  available (e.g. running outside a git checkout).

If you want credit under a handle other than your git commit name,
add `contributor: your-handle` to the YAML.

## Contributors

<!-- CONTRIBUTORS:START -->
Thanks to everyone who has contributed benchmark runs:

- **LearningCircuit** — 2 submissions
- **kwhyte7** — 1 submission
<!-- CONTRIBUTORS:END -->

See [`CONTRIBUTORS.md`](CONTRIBUTORS.md) for the full list (auto-generated).

## Local development

```bash
# Install dependencies (pyyaml is the only hard requirement)
pip install pyyaml

# Run unit tests (uses stdlib unittest, no pytest required)
python -m unittest tests.test_scripts -v

# Validate all submissions
python scripts/validate_yamls.py

# Validate a specific file
python scripts/validate_yamls.py results/simpleqa/source-based/serper/qwen3.5-9b_2026-04-06.yaml

# Regenerate leaderboards locally
python scripts/build_leaderboards.py

# Dry-run the HF sync
python scripts/sync_to_hf.py --dry-run
```

## Setting up the HF sync (maintainers)

1. Create a write token on Hugging Face with access to
   `local-deep-research/ldr-benchmarks`
2. Add it as a repo secret on GitHub named `HF_TOKEN`
3. The `publish.yml` workflow picks it up automatically on merge to main

## Attribution

- **SimpleQA** © OpenAI, MIT License
- **BrowseComp** © OpenAI
- **xbench** © xbench team
- **Local Deep Research** © the LDR community

## Citation

If you use this dataset in published work, please cite both the
individual benchmarks (see the *Attribution* section) and this
collection:

```bibtex
@misc{ldr_community_benchmarks,
  title        = {LDR Community Benchmarks},
  author       = {The Local Deep Research community},
  year         = {2026},
  publisher    = {GitHub / Hugging Face},
  howpublished = {\url{https://github.com/LearningCircuit/ldr-benchmarks}}
}
```

## License

**TBD.** License not yet chosen — likely CC BY 4.0 for the whole repo,
or MIT, pending discussion. Individual benchmark datasets (SimpleQA,
BrowseComp, xbench) retain their own upstream licenses regardless —
see the *Attribution* section.

# Benchmark Methodology

This document explains how to interpret LDR benchmark results, how
much to trust a reported number, and what conditions must hold for a
comparison between two runs to be valid.

For a quick orientation, the README's
[Considerations section](README.md#considerations-for-using-the-data)
has a condensed version of the same material.

---

## What is being measured

LDR benchmarks measure how accurately the system answers factual
questions when it has access to a live search engine. The score is the
fraction of questions where an LLM grader judges the system's final
answer to match the reference answer.

This is **not** a measure of the underlying language model's knowledge.
It measures the full pipeline: query generation, search retrieval,
context synthesis, and final answer extraction — all in combination.
Changing any one of those components (model, strategy, search engine,
prompt template) changes what the score measures.

---

## Confidence intervals for a single run

A reported accuracy of "91%" is a point estimate. The true accuracy
could be higher or lower depending on which questions happened to be
sampled. The Wilson score interval gives the statistically correct
range at 95% confidence:

```
center     = (p̂ + z²/2n) / (1 + z²/n)
half-width = z × sqrt(p̂(1−p̂)/n + z²/4n²) / (1 + z²/n)

where  p̂ = observed accuracy (e.g. 0.91)
       n  = number of examples tested
       z  = 1.96 for 95% confidence
```

Approximate 95% margins of error at common sample sizes:

| Examples (n) | ~70% accuracy | ~85% accuracy | ~91% accuracy | ~95% accuracy |
|---|---|---|---|---|
| 20  | ±21% | ±17% | ±14% | ±10% |
| 50  | ±13% | ±10% | ±8%  | ±6%  |
| 100 | ±9%  | ±7%  | ±6%  | ±4%  |
| 200 | ±6%  | ±5%  | ±4%  | ±3%  |
| 500 | ±4%  | ±3%  | ±3%  | ±2%  |

**Practical guidance:**
- A run of 20 questions has an uncertainty window of ±14–21%. A "91%"
  result plausibly spans 77–100%. Treat it as a rough sanity check only.
- 100 examples is the minimum before drawing any conclusion from a run.
- 200+ examples is the minimum before comparing two configurations.
- Results clustered above 90% (as most LDR submissions are) have tighter
  absolute intervals: at n=300 with 91% accuracy the margin is roughly
  ±3–4 pp.

---

## Comparing two configurations

To tell whether configuration A is genuinely better than configuration
B, the observed difference needs to be larger than the noise from both
runs combined. The table below shows how many examples each
configuration needs (run independently on the same question set via the
same seed) to reliably detect a given absolute accuracy difference at
80% statistical power (α = 0.05, two-sided):

| Difference to detect       | Examples needed per config |
|---|---|
| 5 pp (e.g., 85% vs 90%)   | ~680 |
| 10 pp (e.g., 80% vs 90%)  | ~200 |
| 15 pp (e.g., 75% vs 90%)  | ~90  |

**Rule of thumb:** If the observed gap between two runs is smaller than
the margin of error for either run (see the table above), treat the
results as a tie.

**Practical implication for high-accuracy runs:** When results are
clustered around 90–95%, even a 200-question run can only reliably
detect a ~10 pp difference. If you are trying to distinguish between,
say, 91% and 93%, you would need closer to 680 questions per
configuration — and even then grader noise (see below) will obscure
differences smaller than ~2–3 pp.

---

## When two runs cannot be compared

Statistical power is only one requirement. Even with large sample sizes,
a comparison is unreliable if **any** of the following differ between
the two runs:

| Factor | Why it matters |
|---|---|
| **LDR version** | Search logic, prompt templates, and result filtering change between releases. Two runs on different versions measure different pipelines. |
| **Strategy** | `focused_iteration` and `source_based` answer questions differently by design. Their scores measure different things and are not interchangeable. |
| **Grader model** | Changing the evaluation LLM changes what "correct" means. The same system response may grade differently under a different grader. |
| **Random seed / question sample** | Some subsets of SimpleQA are inherently easier than others. Always use `--seed 42` (or any fixed seed) consistently across compared runs. |
| **Search engine** | Tavily, SearXNG, Serper, and Brave retrieve different content. Engine latency also affects what gets retrieved within per-query time limits. |

Treat each combination of `(ldr_version, strategy, search_engine,
grader_model, seed)` as a distinct experimental condition. Only compare
runs within the same condition.

---

## Evaluator LLM error

The grader LLM (default: Claude 3.7 Sonnet via OpenRouter) is not
perfect. On SimpleQA-style questions it mis-grades approximately 1% of
responses, consistent with calibration results reported in the original
SimpleQA paper for similarly capable graders.

What this means in practice:

| Run size | Expected grading errors | Smallest detectable real difference |
|---|---|---|
| 100 examples | ~1 question | ~3–4 pp (1 pp is pure noise) |
| 200 examples | ~2 questions | ~2–3 pp |
| 500 examples | ~5 questions | ~2 pp |

The grader tends to be conservative — it marks ambiguous or partially
correct matches as incorrect — so reported accuracy is a slight
underestimate of true accuracy.

**Do not optimize for differences smaller than ~2–3 pp on runs under
500 examples.** The signal is not there.

---

## Hands-on advice

### Starting a new benchmark run

1. **Fix your seed.** Use a constant seed. An unfixed seed
   means each run samples a different subset of questions, making reruns
   incomparable.
2. **Start small.** Run 20–50 questions first to confirm your search
   engine is returning results and the grader is producing sensible
   output. Look at a handful of graded examples, not just the summary
   score.
3. **Check search retrieval before trusting accuracy numbers.** If
   `average_results_per_query` is 0 or very low, the model is answering
   from memory, not from search. The accuracy number then measures the
   model and not LDR.
4. **Scale up only after sanity checks pass.** 100 examples for a
   single-configuration result; 200+ if you plan to compare
   configurations.

### Interpreting a submitted result

- Look at `total_questions`. A run of fewer than 100 questions
  should be read as "approximately X%" with wide error bars, not as a
  precise figure.
- Check `ldr_version`, `strategy`, `search_engine`, and
  `evaluator.model`. These four fields define the experimental
  condition. Only compare rows where all four match.
- If `hardware` fields are blank, timing numbers (`avg_time_per_question`)
  cannot be meaningfully compared to other submissions.
- A result with `total_tokens_used` filled in is more reproducible: you
  can estimate cost and check whether the run hit context limits.

### Comparing two configurations yourself

1. Decide in advance what difference size you care about (e.g., "I want
   to know if strategy B is more than 10 pp better than strategy A").
2. Look up the required sample size from the table above (~200 per
   config for 10 pp).
3. Run both configurations on the **same question set** (same seed).
4. Check: is the observed difference greater than the margin of error
   for each run individually? If not, it is noise.
5. Check: is the observed difference greater than ~2–3 pp? If not, it
   may be grader noise even if statistically "significant".

### When a result looks surprisingly good or bad

- **Suspiciously high accuracy (>95%):** Check `total_questions`. A
  small sample can produce any score by chance. Also verify the grader
  model — a lenient grader inflates scores.
- **Suspiciously low accuracy (<70%):** Check that search results are
  actually being retrieved. Zero or near-zero `average_results_per_query`
  or repeated search failures in `test_details` are the most common
  cause.
- **Very fast processing times:** Usually indicates the search step is
  being skipped or timing out silently.
- **Score drops sharply between LDR versions:** Check the changelog for
  that version. Prompt template changes and result-filtering changes have
  historically caused 5–10 pp swings that have nothing to do with the
  model or search engine.

---

## Pre-flight checklist

Before acting on a benchmark result or publishing a comparison:

- [ ] `total_questions` ≥ 100 for a single-configuration result
- [ ] `total_questions` ≥ 200 for a head-to-head comparison
- [ ] Same `--seed` used across all compared runs
- [ ] Same `ldr_version`, `strategy`, `search_engine`, and
      `evaluator.model` across compared runs
- [ ] Observed difference > margin of error for each individual run
- [ ] Observed difference > ~2–3 pp (minimum above grader noise floor)
- [ ] `average_results_per_query` > 0 (search is actually running)
- [ ] Reviewed a sample of graded examples, not just the headline score

---

## Adding a new benchmark dataset

When LDR adds support for a new dataset, update the `BENCHMARKS`
whitelist in **both** `scripts/validate_yamls.py` and
`scripts/build_leaderboards.py`, and document here:

- Whether per-question examples may be shared (see sharing policy in
  README)
- The canonical dataset ID used in LDR's registry
- Any dataset-specific interpretation notes (e.g., question difficulty
  distribution, known contamination risks)

Keep `canonical_id` in sync with LDR's
`src/local_deep_research/benchmarks/datasets/__init__.py`.

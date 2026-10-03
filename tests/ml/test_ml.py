"""Features, dataset generation, policies, models and evaluation for ML pass selection."""

from __future__ import annotations

import itertools
import random

import numpy as np
import pytest

from forgecompile.driver import build_ir
from forgecompile.ir.interpreter import run_module
from forgecompile.ir.printer import format_module
from forgecompile.ml.dataset import (
    ACTIONS,
    LABELS,
    STOP,
    CostEvaluator,
    ProgramSpec,
    StateRecord,
    apply_pass,
    clone_module,
    record_from_json,
    record_to_json,
    trajectory,
)
from forgecompile.ml.evaluate import evaluate_policies, markdown_summary, summarize
from forgecompile.ml.features import FEATURE_GROUPS, FEATURE_NAMES, extract_features, feature_vector
from forgecompile.ml.models import feature_columns, fit, make_models, score, select_model
from forgecompile.ml.policies import (
    FixedPipelinePolicy,
    ModelPolicy,
    OraclePolicy,
    RandomPolicy,
    frequency_order,
    schedule,
)
from forgecompile.testing.program_generator import LOOP_HEAVY, generate_program

LOOPY = """
fn main() -> int {
    let a: [int; 8];
    let s = 0;
    for i in 0..8 { a[i] = i * 3; s = s + a[i] + 2 * 5; }
    print(s);
    return 0;
}
"""


def program(source: str = LOOPY, name: str = "loopy") -> ProgramSpec:
    return ProgramSpec(name, source, "generated")


# ----------------------------------------------------------------------------- features


def test_feature_names_and_groups_are_consistent() -> None:
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    assert sum(len(v) for v in FEATURE_GROUPS.values()) == len(FEATURE_NAMES)
    features = extract_features(build_ir(LOOPY))
    assert list(features) == FEATURE_NAMES
    assert len(feature_vector(build_ir(LOOPY))) == len(FEATURE_NAMES)


def test_features_detect_optimization_opportunities() -> None:
    raw = extract_features(build_ir(LOOPY))
    assert raw["n_loops"] == 1 and raw["max_loop_depth"] == 1
    assert raw["n_copies"] > 0  # copyprop opportunity
    assert raw["n_constant_operand_insts"] > 0  # `2 * 5` is foldable
    assert raw["n_boundschecks"] == 2  # a[i] in the store and in the load
    assert abs(sum(raw[name] for name in FEATURE_GROUPS["opcodes"]) - 1.0) < 1e-9
    module = build_ir(LOOPY)
    apply = apply_pass(module, "copyprop")
    canonical = extract_features(apply)
    assert canonical["n_copies"] == 0
    assert canonical["n_basic_ivs"] == 1  # visible only after copyprop (D-023)
    assert canonical["frac_boundschecks_on_iv"] == pytest.approx(1.0)  # both index with i
    assert canonical["n_iv_multiplies"] == 1  # i * 3


def test_features_on_generated_and_example_programs() -> None:
    for seed in range(15):
        vector = feature_vector(build_ir(generate_program(seed, LOOP_HEAVY)))
        assert all(np.isfinite(vector)) and all(v >= 0 for v in vector)


def test_training_profile_programs_do_not_trap() -> None:
    # D-036: trapping programs truncate their cost, so the ML workload profile emits none.
    for seed in range(100_000, 100_040):
        assert run_module(build_ir(generate_program(seed, LOOP_HEAVY))).trap is None


def test_feature_columns_ablation() -> None:
    all_cols = feature_columns()
    no_loops = feature_columns(("loops",))
    assert len(all_cols) - len(no_loops) == len(FEATURE_GROUPS["loops"])
    with pytest.raises(ValueError):
        feature_columns(("nonsense",))


# ----------------------------------------------------------------------------- dataset


def test_clone_is_independent_and_identical() -> None:
    module = build_ir(LOOPY)
    copy = clone_module(module)
    assert format_module(copy) == format_module(module)
    apply_pass(copy, "dce")
    assert format_module(module) == format_module(build_ir(LOOPY))


def test_cost_evaluator_caches_by_ir() -> None:
    evaluator = CostEvaluator("cost")
    module = build_ir(LOOPY)
    first = evaluator(module)
    assert evaluator(clone_module(module)) == first
    assert evaluator.evaluations == 1
    assert CostEvaluator("steps")(module) < first  # weighted cost exceeds the plain count here


def test_trajectory_records_complete_outcome_tables() -> None:
    records = trajectory(
        program(), steps=6, epsilon=0.0, rng=random.Random(0), evaluator=CostEvaluator()
    )
    assert records and records[0].step == 0
    for record in records:
        assert set(record.outcomes) == set(ACTIONS)
        assert record.label in LABELS
        if record.label != STOP:
            assert record.outcomes[record.label] < record.cost
    # Greedy walk (epsilon = 0): each recorded cost is the previous best outcome.
    for prev, nxt in itertools.pairwise(records):
        assert nxt.cost == pytest.approx(prev.outcomes[prev.taken])
    assert records[-1].taken == STOP or len(records) == 6


def test_record_json_round_trip() -> None:
    record = trajectory(program(), 2, 0.0, random.Random(0), CostEvaluator())[0]
    restored = record_from_json(record_to_json(record))
    assert restored == record and restored.label == record.label


def test_label_is_stop_when_nothing_helps() -> None:
    record = StateRecord("p", "generated", 0, [0.0], 10.0, 10.0, {a: 10.0 for a in ACTIONS}, "")
    assert record.label == STOP
    better = StateRecord(
        "p", "generated", 0, [0.0], 10.0, 10.0, {**record.outcomes, "dce": 9.0}, ""
    )
    assert better.label == "dce" and better.gains()["dce"] == pytest.approx(0.1)


# ----------------------------------------------------------------------------- policies


def test_fixed_and_random_policies() -> None:
    fixed = schedule(FixedPipelinePolicy("p", ["copyprop", "dce"]), build_ir(LOOPY), max_steps=10)
    assert fixed.actions == ["copyprop", "dce"]
    r1 = schedule(RandomPolicy("r", 5, seed=3), build_ir(LOOPY))
    r2 = schedule(RandomPolicy("r", 5, seed=3), build_ir(LOOPY))
    assert r1.actions == r2.actions and len(r1.actions) == 5


def test_oracle_policy_is_greedy_optimal_per_step() -> None:
    evaluator = CostEvaluator()
    result = schedule(OraclePolicy(evaluator), build_ir(LOOPY), max_steps=12)
    assert evaluator(result.module) < evaluator(build_ir(LOOPY))
    assert result.actions[0] in ACTIONS


class _StubbornRanker:
    """Always ranks a pass that does nothing after the first application first."""

    def rank(self, features: list[float]) -> list[str]:
        return ["simplifycfg", *[a for a in ACTIONS if a != "simplifycfg"], STOP]


def test_model_policy_never_retries_a_pass_in_the_same_state() -> None:
    # No pass changes this trivial program, so the state never changes: the policy must
    # try each pass exactly once, then stop (instead of looping on simplifycfg forever).
    result = schedule(
        ModelPolicy(_StubbornRanker()), build_ir("fn main() { print(1); }"), max_steps=30
    )
    assert sorted(result.actions) == sorted(ACTIONS)


def test_frequency_order() -> None:
    def rec(label_pass: str) -> StateRecord:
        outcomes = {a: 10.0 for a in ACTIONS} | {label_pass: 5.0}
        return StateRecord("p", "g", 0, [0.0], 10.0, 10.0, outcomes, "")

    order = frequency_order([rec("dce"), rec("dce"), rec("cse")])
    assert order[:2] == ["dce", "cse"] and set(order) == set(ACTIONS)


# ----------------------------------------------------------------------------- models + evaluation


@pytest.fixture(scope="module")
def small_dataset() -> list[StateRecord]:
    evaluator = CostEvaluator()
    rng = random.Random(0)
    records: list[StateRecord] = []
    for seed in range(12):
        records += trajectory(
            ProgramSpec(f"g{seed}", generate_program(seed, LOOP_HEAVY), "generated"),
            4,
            0.3,
            rng,
            evaluator,
        )
    return records


def test_models_fit_score_and_rank(small_dataset: list[StateRecord]) -> None:
    train, val = small_dataset[: len(small_dataset) // 2], small_dataset[len(small_dataset) // 2 :]
    for name, estimator in make_models(0).items():
        model = fit(name, estimator, train, feature_columns())
        metrics = score(model, val)
        assert 0.0 <= metrics["accuracy"] <= 1.0 and metrics["mean_regret"] >= 0.0
        assert set(model.rank(val[0].features)) == set(LABELS)
    selected, scores = select_model(train, val, seed=0)
    assert selected.name in scores


def test_evaluate_policies_end_to_end() -> None:
    evaluator = CostEvaluator()
    programs = [program(), program("fn main() { let x = 2 * 3; print(x); }", "tiny")]
    outcomes = evaluate_policies(
        programs,
        [
            lambda: FixedPipelinePolicy("O1", ["constfold", "copyprop", "dce"]),
            lambda: OraclePolicy(evaluator),
        ],
        evaluator,
    )
    assert len(outcomes) == 4 and all(o.ratio <= 1.0 for o in outcomes)
    assert all(o.initial_size > 0 and o.final_size > 0 for o in outcomes)
    table = summarize(outcomes)
    assert "oracle-greedy" in table["all"]
    assert "| all |" in markdown_summary(table)

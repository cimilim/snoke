from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.model.bayesian import BayesianUpdater
from app.model.engine import CravingEngine
from app.model.features import Activity, AppCategory, Bucket, FeatureExtractor, StressLevel
from app.model.rules import RuleLayer
from app.model.state_space import CravingModel, CravingModelParameters
from app.model.weaning import BudgetState, WeaningPlanner
from app.models import Event


def test_feature_extractor_weekend_and_hour_block() -> None:
    fx = FeatureExtractor()
    saturday_9am = datetime(2026, 4, 18, 9, 30, tzinfo=UTC)  # Saturday
    b = fx.extract(saturday_9am, {"active_app": "Firefox", "active_title": "twitter.com"})
    assert b.hour_block == 4
    assert b.weekend is True
    assert b.app_category is AppCategory.social


def test_feature_extractor_activity_from_idle() -> None:
    fx = FeatureExtractor()
    now = datetime(2026, 4, 20, 14, 0, tzinfo=UTC)
    b = fx.extract(now, {"idle_seconds": 1200})
    assert b.activity is Activity.still


def test_bayesian_prior_mean_reflects_hour_block() -> None:
    up = BayesianUpdater()
    morning = Bucket(hour_block=4, weekend=False, activity=Activity.still,
                     stress=StressLevel.unknown, app_category=AppCategory.other)
    night = Bucket(hour_block=0, weekend=False, activity=Activity.still,
                   stress=StressLevel.unknown, app_category=AppCategory.other)
    post_morning = up.posterior(morning, {})
    post_night = up.posterior(night, {})
    assert post_morning.mean > post_night.mean


def test_bayesian_fit_updates_posterior_toward_ones() -> None:
    up = BayesianUpdater()
    now = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    bucket = Bucket(hour_block=5, weekend=False, activity=Activity.still,
                    stress=StressLevel.low, app_category=AppCategory.work)
    prior = up.posterior(bucket, {}).mean

    obs = [(bucket, True, now - timedelta(hours=h)) for h in range(20)]
    stats = up.fit(obs, now)
    updated = up.posterior(bucket, stats).mean
    assert updated > prior


def test_rule_layer_reduces_after_recent_cigarette() -> None:
    rules = RuleLayer()
    now = datetime(2026, 4, 20, 14, 0, tzinfo=UTC)
    adj = rules.adjust(
        base_p=0.6,
        now=now,
        recent_cigarettes=[now - timedelta(minutes=8)],
        recent_tags=[],
    )
    # factor should dampen probability
    assert adj.factor < 1.0
    assert adj.reasons  # contains explanation


def test_rule_layer_boosts_on_coffee() -> None:
    rules = RuleLayer()
    now = datetime(2026, 4, 20, 14, 0, tzinfo=UTC)
    adj = rules.adjust(
        base_p=0.3,
        now=now,
        recent_cigarettes=[],
        recent_tags=[("coffee", now - timedelta(minutes=5))],
    )
    assert adj.factor > 1.0
    assert any("Kaffee" in r for r in adj.reasons)


def test_weaning_planner_respects_weaning_rate() -> None:
    p = WeaningPlanner()
    target = p.target_for_today(rolling_avg_7d=20.0, weaning_rate_pct=10, baseline=20)
    assert target == 18  # 20 * 0.9

    status = p.status(rolling_avg_7d=20, smoked_today=17,
                       weaning_rate_pct=10, baseline=20)
    assert status.target_today == 18
    assert status.state is BudgetState.close_to_limit

    status = p.status(rolling_avg_7d=20, smoked_today=19,
                       weaning_rate_pct=10, baseline=20)
    assert status.state is BudgetState.over_budget


def test_weaning_planner_cold_start_uses_baseline() -> None:
    p = WeaningPlanner()
    target = p.target_for_today(rolling_avg_7d=0, weaning_rate_pct=5, baseline=20)
    assert target == 19  # 20 * 0.95


def test_weaning_planner_blends_baseline_and_rolling_average() -> None:
    p = WeaningPlanner()
    target = p.target_for_today(rolling_avg_7d=0.86, weaning_rate_pct=5, baseline=13)
    # Smooth blend prevents unrealistically low target when short-term average is tiny.
    assert target == 9


def test_state_space_model_returns_required_output_fields() -> None:
    model = CravingModel()
    out = model.update(dt=1.0, nicotine=0.0, reward=0.0, stress=0.3, cue=0.4)
    assert set(out.keys()) == {"craving_probability", "dopamine", "withdrawal", "habit"}
    assert 0.0 <= out["craving_probability"] <= 1.0
    assert -2.0 <= out["dopamine"] <= 2.0
    assert 0.0 <= out["withdrawal"] <= 2.0
    assert 0.0 <= out["habit"] <= 1.0


def test_state_space_dt_controls_exponential_decay() -> None:
    model_short = CravingModel()
    model_long = CravingModel()

    # identical input but different dt should produce different dopamine decay.
    out_short = model_short.update(dt=0.1, nicotine=0.2, reward=0.0, stress=0.0, cue=0.0)
    out_long = model_long.update(dt=2.0, nicotine=0.2, reward=0.0, stress=0.0, cue=0.0)
    assert out_long["dopamine"] < out_short["dopamine"]


def test_state_space_nicotine_lowers_withdrawal_and_raises_dopamine() -> None:
    model = CravingModel()
    base = model.get_state()
    out = model.update(dt=0.5, nicotine=1.0, reward=0.0, stress=0.0, cue=0.0)
    assert out["dopamine"] >= base["dopamine"]
    assert out["withdrawal"] <= 1.0


def test_state_space_action_hook_modifies_state() -> None:
    model = CravingModel()
    no_action = model.update(dt=0.5, nicotine=0.0, reward=0.0, stress=0.7, cue=0.3)
    model.reset()
    with_action = model.update(
        dt=0.5,
        nicotine=0.0,
        reward=0.0,
        stress=0.7,
        cue=0.3,
        action={"dopamine_boost": 0.2, "withdrawal_relief": 0.2},
    )
    assert with_action["dopamine"] > no_action["dopamine"]
    assert with_action["withdrawal"] < no_action["withdrawal"]


def test_optional_kalman_update_runs() -> None:
    model = CravingModel(CravingModelParameters(enable_kalman=True))
    out = model.update(
        dt=1.0,
        nicotine=0.0,
        reward=0.0,
        stress=0.8,
        cue=0.8,
        observed_craving=0.9,
    )
    assert 0.0 <= out["craving_probability"] <= 1.0


def test_nutrition_activity_affects_craving_inputs_and_action() -> None:
    engine = CravingEngine()
    ev = Event(
        user_id="u-1",
        client_uuid="act-00000001",
        kind="nutrition_activity",
        occurred_at=datetime.now(UTC),
        payload={"sport_type": "joggen", "minutes": 45, "kcal_burned": 420},
    )
    nic, rew, stress, cue = engine._inputs_for_step(ev, context={})
    assert nic == 0.0
    assert rew > 0.25
    assert 0.0 <= stress <= 1.0
    assert 0.0 <= cue <= 1.0

    action = engine._event_action(ev)
    assert action is not None
    assert action["dopamine_boost"] > 0.0
    assert action["withdrawal_relief"] > 0.0

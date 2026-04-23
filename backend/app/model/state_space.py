"""Torch-based dynamic latent-state craving model.

The model keeps the backend-friendly API (`update/get_state/reset`) while also
supporting differentiable sequence training via `forward` and `run_sequence`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
import torch.nn as nn


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _sigmoid(x: float) -> float:
    return float(torch.sigmoid(torch.tensor(float(x), dtype=torch.float32)).item())


def estimate_half_life(weight_kg: float, body_fat: float) -> float:
    base = 2.0
    fat_factor = 1.0 + 0.5 * body_fat
    weight_factor = 70.0 / max(35.0, weight_kg)
    return max(0.25, base * fat_factor * weight_factor)


def dopamine_sensitivity(body_fat: float, age_years: int) -> float:
    base = 1.0
    fat_effect = 1.0 - 0.3 * body_fat
    age_effect = 1.0 - 0.002 * age_years
    return float(max(0.5, min(1.5, base * fat_effect * age_effect)))


def nicotine_effect_from_mg(dose_mg: torch.Tensor, weight_kg: torch.Tensor, kd: float) -> torch.Tensor:
    vd = 2.5 * torch.clamp(weight_kg, min=35.0)
    conc = dose_mg / vd
    return conc / (conc + float(kd))


@dataclass(slots=True)
class CravingModelParameters:
    """Configurable parameters for the dynamic state-space model."""

    lambda_nicotine: float = 0.35
    k_dopamine: float = 0.35
    k_habit_decay: float = 0.006
    k_withdrawal: float = 0.06
    decay_withdrawal: float = 0.03
    habit_learning: float = 0.03

    alpha_nicotine: float = 0.75
    alpha_reward: float = 0.25
    beta_stress: float = 0.40

    k_dopamine_fast: float = 1.10
    k_dopamine_slow: float = 0.08
    dopamine_fast_weight: float = 0.45
    alpha_nicotine_fast: float = 0.90
    alpha_nicotine_slow: float = 0.30
    alpha_reward_fast: float = 0.22
    alpha_reward_slow: float = 0.10
    beta_stress_fast: float = 0.45
    beta_stress_slow: float = 0.18

    w_D: float = 2.0
    w_W: float = 2.4
    w_H: float = 1.6
    w_stress: float = 0.9
    w_cue: float = 0.9
    bias: float = 0.0

    enable_kalman: bool = False
    kalman_process_noise: float = 0.02
    kalman_observation_noise: float = 0.08

    default_action_dopamine_boost: float = 0.12
    default_action_withdrawal_relief: float = 0.10
    # Personalized profile inputs
    weight_kg: float = 75.0
    height_cm: float = 175.0
    body_fat: float = 0.20
    age_years: int = 30
    cigarette_dose_mg: float = 1.5
    nicotine_kd: float = 0.02


class CravingModel(nn.Module):
    def __init__(self, parameters: CravingModelParameters | None = None) -> None:
        super().__init__()
        self.params = parameters or CravingModelParameters()
        self.dt = 1.0 / 60.0  # hours, default 60-second simulation step

        def p(value: float) -> nn.Parameter:
            return nn.Parameter(torch.tensor(float(value), dtype=torch.float32))

        personalized = self._personalized(self.params)

        self.lambda_nicotine = p(personalized["lambda_nicotine"])
        self.k_dopamine_fast = p(self.params.k_dopamine_fast)
        self.k_dopamine_slow = p(self.params.k_dopamine_slow)
        self.alpha_nic_fast = p(personalized["alpha_nicotine_fast"])
        self.alpha_nic_slow = p(personalized["alpha_nicotine_slow"])
        self.alpha_reward_fast = p(self.params.alpha_reward_fast)
        self.alpha_reward_slow = p(self.params.alpha_reward_slow)
        self.beta_stress_fast = p(self.params.beta_stress_fast)
        self.beta_stress_slow = p(self.params.beta_stress_slow)
        self.k_withdrawal = p(personalized["k_withdrawal"])
        self.decay_withdrawal = p(self.params.decay_withdrawal)
        self.k_habit_decay = p(self.params.k_habit_decay)
        self.habit_learning = p(personalized["habit_learning"])
        self.w_fast = p(self.params.dopamine_fast_weight)

        self.w_D = p(self.params.w_D)
        self.w_W = p(self.params.w_W)
        self.w_H = p(self.params.w_H)
        self.w_stress = p(self.params.w_stress)
        self.w_cue = p(self.params.w_cue)
        self.bias = p(self.params.bias)
        self._weight_kg = p(self.params.weight_kg)
        self._height_cm = p(self.params.height_cm)
        self._body_fat = p(self.params.body_fat)
        self._age_years = p(float(self.params.age_years))

        self._D_fast = torch.tensor(0.45, dtype=torch.float32)
        self._D_slow = torch.tensor(0.45, dtype=torch.float32)
        self._W = torch.tensor(0.25, dtype=torch.float32)
        self._H = torch.tensor(0.35, dtype=torch.float32)
        self._P = torch.eye(3, dtype=torch.float32) * 0.10
        self._last_probability = 0.5
        self._last_nicotine_effect = 0.0

    def _device(self) -> torch.device:
        return self.lambda_nicotine.device

    def clone(self) -> CravingModel:
        p = CravingModelParameters(
            lambda_nicotine=float(self.lambda_nicotine.detach().item()),
            k_dopamine=self.params.k_dopamine,
            k_habit_decay=float(self.k_habit_decay.detach().item()),
            k_withdrawal=float(self.k_withdrawal.detach().item()),
            decay_withdrawal=float(self.decay_withdrawal.detach().item()),
            habit_learning=float(self.habit_learning.detach().item()),
            alpha_nicotine=self.params.alpha_nicotine,
            alpha_reward=self.params.alpha_reward,
            beta_stress=self.params.beta_stress,
            k_dopamine_fast=float(self.k_dopamine_fast.detach().item()),
            k_dopamine_slow=float(self.k_dopamine_slow.detach().item()),
            dopamine_fast_weight=float(self.w_fast.detach().item()),
            alpha_nicotine_fast=float(self.alpha_nic_fast.detach().item()),
            alpha_nicotine_slow=float(self.alpha_nic_slow.detach().item()),
            alpha_reward_fast=float(self.alpha_reward_fast.detach().item()),
            alpha_reward_slow=float(self.alpha_reward_slow.detach().item()),
            beta_stress_fast=float(self.beta_stress_fast.detach().item()),
            beta_stress_slow=float(self.beta_stress_slow.detach().item()),
            w_D=float(self.w_D.detach().item()),
            w_W=float(self.w_W.detach().item()),
            w_H=float(self.w_H.detach().item()),
            w_stress=float(self.w_stress.detach().item()),
            w_cue=float(self.w_cue.detach().item()),
            bias=float(self.bias.detach().item()),
            enable_kalman=self.params.enable_kalman,
            kalman_process_noise=self.params.kalman_process_noise,
            kalman_observation_noise=self.params.kalman_observation_noise,
            default_action_dopamine_boost=self.params.default_action_dopamine_boost,
            default_action_withdrawal_relief=self.params.default_action_withdrawal_relief,
            weight_kg=float(self._weight_kg.detach().item()),
            height_cm=float(self._height_cm.detach().item()),
            body_fat=float(self._body_fat.detach().item()),
            age_years=int(round(float(self._age_years.detach().item()))),
            cigarette_dose_mg=self.params.cigarette_dose_mg,
            nicotine_kd=self.params.nicotine_kd,
        )
        other = CravingModel(p).to(self._device())
        other._D_fast = self._D_fast.detach().clone()
        other._D_slow = self._D_slow.detach().clone()
        other._W = self._W.detach().clone()
        other._H = self._H.detach().clone()
        other._P = self._P.detach().clone()
        other._last_probability = self._last_probability
        other._last_nicotine_effect = self._last_nicotine_effect
        return other

    def reset(self, state: tuple[float, float, float] | None = None) -> None:
        with torch.no_grad():
            if state is None:
                d, w, h = 0.45, 0.25, 0.35
            else:
                d, w, h = _clip01(state[0]), _clip01(state[1]), _clip01(state[2])
            device = self._device()
            self._D_fast = torch.tensor(d, dtype=torch.float32, device=device)
            self._D_slow = torch.tensor(d, dtype=torch.float32, device=device)
            self._W = torch.tensor(w, dtype=torch.float32, device=device)
            self._H = torch.tensor(h, dtype=torch.float32, device=device)
            self._P = torch.eye(3, dtype=torch.float32, device=device) * 0.10
            self._last_probability = float(
                torch.sigmoid(
                    -self.w_D * ((self.w_fast * self._D_fast) + (1 - self.w_fast) * self._D_slow)
                    + self.w_W * self._W
                    + self.w_H * self._H
                    + self.bias
                ).item()
            )
            self._last_nicotine_effect = 0.0

    def forward(
        self, inputs: dict[str, torch.Tensor], state: dict[str, torch.Tensor]
    ) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        dt = inputs.get("dt")
        if dt is None:
            dt = torch.tensor(self.dt, dtype=torch.float32, device=state["D_fast"].device)
        elif not isinstance(dt, torch.Tensor):
            dt = torch.tensor(float(dt), dtype=torch.float32, device=state["D_fast"].device)
        return self._forward_step(inputs=inputs, state=state, dt=dt, action=None)

    def update(
        self,
        dt: float,
        nicotine: float,
        reward: float,
        stress: float,
        cue: float,
        action: dict[str, float] | str | None = None,
        observed_craving: float | None = None,
    ) -> dict[str, float]:
        device = self._device()
        dt_t = torch.tensor(max(1e-4, float(dt)), dtype=torch.float32, device=device)
        inputs = {
            "nicotine": torch.tensor(_clip01(nicotine), dtype=torch.float32, device=device),
            "reward": torch.tensor(_clip01(reward), dtype=torch.float32, device=device),
            "stress": torch.tensor(_clip01(stress), dtype=torch.float32, device=device),
            "cue": torch.tensor(_clip01(cue), dtype=torch.float32, device=device),
        }
        state = {
            "D_fast": self._D_fast,
            "D_slow": self._D_slow,
            "W": self._W,
            "H": self._H,
        }
        with torch.no_grad():
            craving_prob, new_state = self._forward_step(inputs=inputs, state=state, dt=dt_t, action=action)
            self._D_fast = new_state["D_fast"].detach()
            self._D_slow = new_state["D_slow"].detach()
            self._W = new_state["W"].detach()
            self._H = new_state["H"].detach()
            self._last_probability = float(craving_prob.detach().item())
            dose_mg = inputs["nicotine"] * float(self.params.cigarette_dose_mg)
            nicotine_effect = nicotine_effect_from_mg(
                dose_mg=dose_mg,
                weight_kg=torch.full_like(dose_mg, float(self._weight_kg.item())),
                kd=self.params.nicotine_kd,
            ) * torch.exp(-self.lambda_nicotine * dt_t)
            self._last_nicotine_effect = float(torch.clamp(nicotine_effect, min=0.0, max=1.0).item())

            if self.params.enable_kalman and observed_craving is not None:
                self._kalman_update(
                    dt=dt_t,
                    stress=inputs["stress"],
                    cue=inputs["cue"],
                    observed_craving=torch.tensor(
                        _clip01(observed_craving), dtype=torch.float32, device=device
                    ),
                )

        D = (self.w_fast * self._D_fast) + ((1 - self.w_fast) * self._D_slow)
        return {
            "craving_probability": float(self._last_probability),
            "dopamine": float(D.item()),
            "withdrawal": float(self._W.item()),
            "habit": float(self._H.item()),
        }

    def get_state(self) -> dict[str, float]:
        D = (self.w_fast * self._D_fast) + ((1 - self.w_fast) * self._D_slow)
        return {
            "craving_probability": float(self._last_probability),
            "dopamine": float(D.item()),
            "withdrawal": float(self._W.item()),
            "habit": float(self._H.item()),
        }

    def simulate(self, steps: list[dict[str, Any]]) -> list[dict[str, float]]:
        trajectory: list[dict[str, float]] = []
        for step in steps:
            out = self.update(
                dt=float(step.get("dt", 1.0)),
                nicotine=float(step.get("nicotine", 0.0)),
                reward=float(step.get("reward", 0.0)),
                stress=float(step.get("stress", 0.0)),
                cue=float(step.get("cue", 0.0)),
                action=step.get("action"),
                observed_craving=step.get("observed_craving"),
            )
            trajectory.append(out)
        return trajectory

    def _resolve_action(self, action: dict[str, float] | str | None) -> tuple[float, float]:
        if action is None:
            return 0.0, 0.0
        if isinstance(action, dict):
            return (
                _clip01(float(action.get("dopamine_boost", 0.0))),
                _clip01(float(action.get("withdrawal_relief", 0.0))),
            )
        return (
            float(self.params.default_action_dopamine_boost),
            float(self.params.default_action_withdrawal_relief),
        )

    @staticmethod
    def _personalized(params: CravingModelParameters) -> dict[str, float]:
        bf = _clip01(params.body_fat)
        age = max(14, int(params.age_years))
        w = max(35.0, float(params.weight_kg))
        t_half = estimate_half_life(weight_kg=w, body_fat=bf)
        sens = dopamine_sensitivity(body_fat=bf, age_years=age)
        lambda_nic = float(torch.log(torch.tensor(2.0)).item() / t_half)
        return {
            "lambda_nicotine": lambda_nic,
            "alpha_nicotine_fast": float(params.alpha_nicotine_fast * sens),
            "alpha_nicotine_slow": float(params.alpha_nicotine_slow * sens),
            "k_withdrawal": float(params.k_withdrawal * (w / 70.0) * (1.0 + bf)),
            "habit_learning": float(params.habit_learning * (1.0 + 0.2 * bf)),
        }

    def _forward_step(
        self,
        inputs: dict[str, torch.Tensor],
        state: dict[str, torch.Tensor],
        dt: torch.Tensor,
        action: dict[str, float] | str | None = None,
    ) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        nicotine = inputs["nicotine"]
        reward = inputs["reward"]
        stress = inputs["stress"]
        cue = inputs["cue"]
        dose_mg = inputs.get("dose_mg")
        if dose_mg is None:
            dose_mg = nicotine * float(self.params.cigarette_dose_mg)
        weight_kg = inputs.get("weight_kg")
        if weight_kg is None:
            weight_kg = torch.full_like(dose_mg, fill_value=float(self._weight_kg.item()))
        elif not isinstance(weight_kg, torch.Tensor):
            weight_kg = torch.full_like(dose_mg, fill_value=float(weight_kg))

        D_fast = state["D_fast"]
        D_slow = state["D_slow"]
        W = state["W"]
        H = state["H"]

        dopamine_boost, withdrawal_relief = self._resolve_action(action)
        dopamine_boost_t = torch.tensor(float(dopamine_boost), dtype=torch.float32, device=nicotine.device)
        withdrawal_relief_t = torch.tensor(
            float(withdrawal_relief), dtype=torch.float32, device=nicotine.device
        )

        nicotine_effect = nicotine_effect_from_mg(
            dose_mg=dose_mg,
            weight_kg=weight_kg,
            kd=self.params.nicotine_kd,
        ) * torch.exp(-self.lambda_nicotine * dt)

        D_fast = (
            D_fast * torch.exp(-self.k_dopamine_fast * dt)
            + self.alpha_nic_fast * nicotine_effect
            + self.alpha_reward_fast * reward
            - self.beta_stress_fast * stress
            + 0.7 * dopamine_boost_t
        )
        D_slow = (
            D_slow * torch.exp(-self.k_dopamine_slow * dt)
            + self.alpha_nic_slow * nicotine_effect
            + self.alpha_reward_slow * reward
            - self.beta_stress_slow * stress
            + 0.3 * dopamine_boost_t
        )
        D = self.w_fast * D_fast + (1 - self.w_fast) * D_slow

        nicotine_binary = (dose_mg > 0).float()
        W = W * torch.exp(-self.decay_withdrawal * dt) + self.k_withdrawal * (1 - nicotine_binary) * dt
        W = W - withdrawal_relief_t

        H = H * torch.exp(-self.k_habit_decay * dt)
        H = H + self.habit_learning * cue * (1 - H)

        D = torch.clamp(D, min=-2.0, max=2.0)
        W = torch.clamp(W, min=0.0, max=2.0)
        H = torch.clamp(H, min=0.0, max=1.0)

        craving_input = (
            -self.w_D * D
            + self.w_W * W
            + self.w_H * H
            + self.w_stress * stress
            + self.w_cue * cue
            + self.bias
        )
        craving_prob = torch.sigmoid(craving_input)

        return craving_prob, {
            "D_fast": D_fast,
            "D_slow": D_slow,
            "W": W,
            "H": H,
        }

    def _kalman_update(
        self,
        dt: torch.Tensor,
        stress: torch.Tensor,
        cue: torch.Tensor,
        observed_craving: torch.Tensor,
    ) -> None:
        with torch.no_grad():
            w_fast = torch.clamp(self.w_fast, min=0.0, max=1.0)
            a_d = w_fast * torch.exp(-self.k_dopamine_fast * dt) + (1 - w_fast) * torch.exp(
                -self.k_dopamine_slow * dt
            )
            a_w = torch.exp(-self.decay_withdrawal * dt)
            a_h = torch.exp(-self.k_habit_decay * dt)
            A = torch.diag(torch.stack([a_d, a_w, a_h]))

            q = max(1e-6, float(self.params.kalman_process_noise))
            r = max(1e-6, float(self.params.kalman_observation_noise))
            Q = torch.eye(3, dtype=torch.float32, device=self._device()) * q
            self._P = A @ self._P @ A.T + Q

            D = (self.w_fast * self._D_fast) + ((1 - self.w_fast) * self._D_slow)
            y_input = (
                -self.w_D * D
                + self.w_W * self._W
                + self.w_H * self._H
                + self.w_stress * stress
                + self.w_cue * cue
                + self.bias
            )
            y_hat = torch.sigmoid(y_input)
            g = y_hat * (1 - y_hat)
            H_obs = torch.tensor(
                [[-float(self.w_D.item()), float(self.w_W.item()), float(self.w_H.item())]],
                dtype=torch.float32,
                device=self._device(),
            ) * g

            S = (H_obs @ self._P @ H_obs.T).squeeze() + r
            if float(S.item()) <= 1e-8:
                return

            K = (self._P @ H_obs.T) / S
            innovation = observed_craving - y_hat
            delta = K[:, 0] * innovation

            prev_D = D.detach().clone()
            D_corr = torch.clamp(D + delta[0], min=-2.0, max=2.0)
            W_corr = torch.clamp(self._W + delta[1], min=0.0, max=2.0)
            H_corr = torch.clamp(self._H + delta[2], min=0.0, max=1.0)

            self._W = W_corr
            self._H = H_corr

            delta_D = D_corr - prev_D
            self._D_fast = self._D_fast + delta_D * w_fast
            self._D_slow = self._D_slow + delta_D * (1 - w_fast)

            I = torch.eye(3, dtype=torch.float32, device=self._device())
            self._P = (I - K @ H_obs) @ self._P

            D_new = (self.w_fast * self._D_fast) + ((1 - self.w_fast) * self._D_slow)
            craving_input = (
                -self.w_D * D_new
                + self.w_W * self._W
                + self.w_H * self._H
                + self.w_stress * stress
                + self.w_cue * cue
                + self.bias
            )
            self._last_probability = float(torch.sigmoid(craving_input).item())


def run_sequence(
    model: CravingModel,
    input_seq: dict[str, torch.Tensor],
    init_state: dict[str, torch.Tensor],
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Run the differentiable model over a time sequence (T, batch)."""
    T = input_seq["nicotine"].shape[0]
    state = init_state
    outputs: list[torch.Tensor] = []
    for t in range(T):
        inputs_t = {k: v[t] for k, v in input_seq.items()}
        out, state = model(inputs_t, state)
        outputs.append(out)
    return torch.stack(outputs), state


def init_state(batch_size: int, device: str = "cpu") -> dict[str, torch.Tensor]:
    """Create initial batch state for sequence training/inference."""
    return {
        "D_fast": torch.zeros(batch_size, device=device),
        "D_slow": torch.zeros(batch_size, device=device),
        "W": torch.zeros(batch_size, device=device),
        "H": torch.zeros(batch_size, device=device),
    }

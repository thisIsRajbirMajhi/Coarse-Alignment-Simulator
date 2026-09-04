# tracking/imm.py - Interacting Multiple Model (IMM) for PAT
# 3 models: Still (low Q), CV (medium Q), Maneuver (high Q)
# All constant-velocity 4-state [x,y,vx,vy], different process noise Q
# Mixing via Markov transition Pi

from __future__ import annotations

import math

import numpy as np

from tracking.kalman import KalmanFilter


class IMMFilter:
    """
    IMM with 3 CV models differing only in process_var.
    - model 0: Still q=2  (stationary / slow drift)
    - model 1: CV    q=12 (nominal, matches old Kalman)
    - model 2: Maneuver q=38 (curved, figure-eight, spiral)
    Transition Pi keeps high self-prob (0.90/0.85) with 5-10% switch.
    """

    def __init__(
        self,
        qs: tuple[float, float, float] = (2.0, 12.0, 38.0),
        meas_var: float = 4.0,
        pi: np.ndarray | None = None,
        initial_cov_scale: float = 500.0,
    ):
        self.qs = tuple(float(q) for q in qs)
        self.meas_var = float(meas_var)
        self.initial_cov_scale = float(initial_cov_scale)
        # Markov transition
        if pi is None:
            self.Pi = np.array(
                [[0.90, 0.05, 0.05],
                 [0.05, 0.85, 0.10],
                 [0.05, 0.10, 0.85]],
                dtype=float,
            )
        else:
            self.Pi = np.asarray(pi, dtype=float)
        self.n = 3
        self.filters: list[KalmanFilter] = [
            KalmanFilter(process_var=self.qs[i], meas_var=self.meas_var, initial_cov_scale=self.initial_cov_scale)
            for i in range(self.n)
        ]
        self.mu = np.array([0.33, 0.34, 0.33], dtype=float)  # mode probs
        self.mu /= np.sum(self.mu)
        self._last_likelihoods = np.ones(self.n, dtype=float) / self.n

    def is_initialized(self) -> bool:
        return all(f.is_initialized() for f in self.filters)

    def init_from_measurement(self, z: tuple[float, float], vel: tuple[float, float] | None = None):
        for f in self.filters:
            f.init_from_measurement(z, vel)
        # after init, set mode probs to favor CV
        self.mu = np.array([0.20, 0.60, 0.20], dtype=float)
        return self.get_pos()

    def _mix(self):
        # interaction: compute mixing probs mu_ij and mixed states
        c = self.Pi.T @ self.mu  # c_j = sum_i Pi_ij * mu_i  (note Pi rows from->to, so transpose)
        # avoid div0
        c = np.maximum(c, 1e-9)
        mu_ij = (self.Pi * self.mu[:, None]) / c[None, :]  # shape n x n, mu_ij = Pi_ij*mu_i / c_j
        # mixed states
        mixed_x = []
        mixed_P = []
        for j in range(self.n):
            # x0_j = sum_i mu_ij * x_i
            x0 = np.zeros(4, dtype=float)
            for i in range(self.n):
                if self.filters[i].x is not None:
                    x0 += float(mu_ij[i, j]) * self.filters[i].x  # type: ignore
            # P0_j = sum_i mu_ij * (P_i + (x_i - x0)(x_i - x0)^T)
            P0 = np.zeros((4, 4), dtype=float)
            for i in range(self.n):
                if self.filters[i].P is not None and self.filters[i].x is not None:
                    dx = (self.filters[i].x - x0).reshape(4, 1)  # type: ignore
                    Pi = self.filters[i].P  # type: ignore
                    P0 += float(mu_ij[i, j]) * (Pi + dx @ dx.T)
            mixed_x.append(x0)
            mixed_P.append(P0)
        return mixed_x, mixed_P, c, mu_ij

    def predict(self, dt: float) -> tuple[float, float] | None:
        if not self.is_initialized():
            return None
        dt = float(dt)
        # mixing before predict
        mixed_x, mixed_P, c, mu_ij = self._mix()
        # set each filter to mixed state then predict
        for j in range(self.n):
            self.filters[j].x = mixed_x[j].copy()
            self.filters[j].P = mixed_P[j].copy()
            self.filters[j]._last_dt = dt
            # need to set _prev_z? keep
            self.filters[j].predict(dt)
        # mode probs after prediction = c (predicted prob)
        self.mu = c / np.sum(c)
        return self.get_pos()

    def update(self, z: tuple[float, float]) -> tuple[float, float]:
        if not self.is_initialized():
            return self.init_from_measurement(z)  # type: ignore
        # each filter update, compute likelihood
        likelihoods = np.zeros(self.n, dtype=float)
        for j in range(self.n):
            # need y and S before update for likelihood
            f = self.filters[j]
            try:
                H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
                y = np.array([float(z[0]), float(z[1])], dtype=float) - H @ f.x  # type: ignore
                S = H @ f.P @ H.T + np.eye(2) * float(f.meas_var)  # type: ignore
                # Gaussian likelihood N(y;0,S)
                det = float(np.linalg.det(S))
                if det <= 1e-9:
                    det = 1e-9
                invS = np.linalg.inv(S)
                exponent = -0.5 * float(y @ invS @ y)
                norm = 1.0 / (2 * math.pi * math.sqrt(det))
                L = float(norm * math.exp(exponent))
                # clamp tiny
                L = max(L, 1e-12)
            except Exception:
                L = 1e-9
            likelihoods[j] = L
            f.update(z)
        # mode prob update: mu_j = c_j * L_j / sum
        # c is from last predict mixing (stored in self.mu after predict)
        # If we are called without predict (should not), use current mu as c
        try:
            # c was stored as mu after predict, so use it
            c = self.mu.copy()
        except Exception:
            c = np.ones(self.n) / self.n
        unnorm = c * likelihoods
        s = float(np.sum(unnorm))
        if s < 1e-12:
            s = 1e-12
        self.mu = unnorm / s
        self._last_likelihoods = likelihoods.copy()
        return self.get_pos()  # type: ignore

    def get_pos(self) -> tuple[float, float] | None:
        if not self.is_initialized():
            return None
        # combined estimate
        try:
            x_comb = np.zeros(4, dtype=float)
            for j in range(self.n):
                if self.filters[j].x is not None:
                    x_comb += float(self.mu[j]) * self.filters[j].x  # type: ignore
            return (float(x_comb[0]), float(x_comb[1]))
        except Exception:
            # fallback to first
            return self.filters[0].get_pos()

    def get_state(self) -> np.ndarray | None:
        if not self.is_initialized():
            return None
        try:
            x_comb = np.zeros(4, dtype=float)
            for j in range(self.n):
                if self.filters[j].x is not None:
                    x_comb += float(self.mu[j]) * self.filters[j].x  # type: ignore
            return x_comb.copy()
        except Exception:
            return None

    def get_state_vector(self) -> np.ndarray | None:
        return self.get_state()

    def get_vel(self) -> tuple[float, float] | None:
        s = self.get_state()
        if s is None:
            return None
        return (float(s[2]), float(s[3]))

    def get_innovation_cov(self) -> np.ndarray | None:
        # combined S = sum mu_j * (H P_j H^T + R)
        if not self.is_initialized():
            return None
        try:
            S_comb = np.zeros((2, 2), dtype=float)
            for j in range(self.n):
                f = self.filters[j]
                if f.P is not None:
                    S = f.get_innovation_cov()
                    if S is not None:
                        S_comb += float(self.mu[j]) * S
            # ensure PD
            S_comb = (S_comb + S_comb.T) * 0.5
            S_comb[0, 0] = max(float(S_comb[0, 0]), 1e-3)
            S_comb[1, 1] = max(float(S_comb[1, 1]), 1e-3)
            return S_comb
        except Exception:
            return None

    def get_mode_probs(self) -> np.ndarray:
        return self.mu.copy()

    def reset(self) -> None:
        for f in self.filters:
            f.reset()
        self.mu = np.array([0.33, 0.34, 0.33], dtype=float)
        self.mu /= np.sum(self.mu)

"""Local gradient-domain boundary matching; no source glyph pixels are sampled."""

from __future__ import annotations

import numpy as np


class MaskedBoundaryMatcher:
    """Harmonic color correction with original pixels as exterior constraints.

    Solve (4I - adjacency) D = exterior(source - candidate), then use G+D
    inside M. Source RGB inside M is never consulted. Matrix-free CG avoids
    introducing a new dependency; bounded residual checks fail closed.
    """

    def __init__(self, mask: np.ndarray, *, max_iterations: int = 1024):
        if (mask.ndim != 2 or mask.dtype != np.bool_ or not mask.any()
                or mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any()):
            raise ValueError("mask must be nonempty boolean interior pixels with an exterior border")
        if type(max_iterations) is not int or not 1 <= max_iterations <= 1024:
            raise ValueError("invalid solver iteration limit")
        self.mask = mask.copy()
        self.max_iterations = max_iterations
        self.y, self.x = np.nonzero(mask)
        self.size = len(self.y)
        if self.size > 20000:
            raise ValueError("mask exceeds bounded local correction size")
        ids = np.full(mask.shape, -1, dtype=np.int32)
        ids[self.y, self.x] = np.arange(self.size)
        self.interior = []
        self.exterior = []
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = self.y + dy, self.x + dx
            neighbor = ids[ny, nx]
            inside = neighbor >= 0
            rows = np.flatnonzero(inside)
            self.interior.append((rows, neighbor[rows]))
            outside_rows = np.flatnonzero(~inside)
            self.exterior.append((outside_rows, ny[outside_rows], nx[outside_rows]))

    def _multiply(self, vector: np.ndarray) -> np.ndarray:
        result = 4.0 * vector
        for rows, neighbors in self.interior:
            result[rows] -= vector[neighbors]
        return result

    def _solve(self, rhs: np.ndarray) -> tuple[np.ndarray, int, float]:
        result = np.zeros_like(rhs)
        residual = rhs.copy()
        direction = residual.copy()
        energy = float(np.sum(residual * residual))
        if np.max(np.abs(residual)) <= 1e-6:
            return result, 0, float(np.max(np.abs(residual)))
        for iteration in range(1, self.max_iterations + 1):
            product = self._multiply(direction)
            denominator = float(np.sum(direction * product))
            if denominator <= 0 or not np.isfinite(denominator):
                raise ValueError("boundary correction failed to converge")
            alpha = energy / denominator
            result += alpha * direction
            residual -= alpha * product
            if np.max(np.abs(residual)) <= 1e-6:
                actual_residual = float(np.max(np.abs(rhs - self._multiply(result))))
                if actual_residual <= 1e-5:
                    return result, iteration, actual_residual
                raise ValueError("boundary correction failed to converge accurately")
            next_energy = float(np.sum(residual * residual))
            direction = residual + (next_energy / energy) * direction
            energy = next_energy
        raise ValueError("boundary correction failed to converge within iteration limit")

    def apply(self, source: np.ndarray, candidate: np.ndarray) -> tuple[np.ndarray, dict]:
        shape = (*self.mask.shape, 3)
        if (source.shape != shape or candidate.shape != shape
                or source.dtype != np.uint8 or candidate.dtype != np.uint8):
            raise ValueError("source/candidate geometry or RGB dtype differs from mask")
        rhs = np.zeros((self.size, 3), dtype=np.float64)
        for rows, y, x in self.exterior:
            rhs[rows] += source[y, x].astype(np.float64) - candidate[y, x].astype(np.float64)
        correction = np.empty_like(rhs)
        iterations, residuals = [], []
        for channel in range(3):
            correction[:, channel], count, residual = self._solve(rhs[:, channel])
            iterations.append(count)
            residuals.append(residual)
        values = candidate[self.mask].astype(np.float64) + correction
        result = source.copy()
        result[self.mask] = np.clip(np.rint(values), 0, 255).astype(np.uint8)
        return result, {
            "iterations": max(iterations), "max_residual": max(residuals),
            "max_abs_correction_rgb": float(np.max(np.abs(correction))),
            "mean_abs_correction_rgb": float(np.mean(np.abs(correction))),
            "clipped_channel_fraction": float(np.mean((values < 0) | (values > 255))),
        }

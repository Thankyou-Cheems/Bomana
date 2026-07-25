"""Reusable integrated and standalone CCRP bombing cue surfaces."""

from __future__ import annotations

import contextlib
import ctypes
import math
import time
import tkinter as tk
from dataclasses import dataclass
from typing import Any

from bomana.config.settings import (
    BallisticPhysicsParams,
    BombConfig,
    HotkeyConfig,
    PanelConfig,
    UIConfig,
)
from bomana.ui.panel_presenter import build_bombing_display_model
from bomana.ui.text_utils import set_elided_text
from bomana.ui.theme import Theme
from bomana.ui.tk_style import style_action_button, style_clickable_surface
from bomana.utils.system import Win32

_WIN32_ACCESS_ERRORS = (OSError, AttributeError)


@dataclass(frozen=True, slots=True)
class CCRPCueProjection:
    """One deterministic target state for the animated convergence cue."""

    gap_ratio: float
    color: str
    status_text: str
    pulse: bool = False
    available: bool = True


def _finite_time_to_release(snapshot: Any) -> float:
    try:
        value = float(getattr(snapshot, "time_to_release", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def _finite_solution_age(snapshot: Any) -> float:
    try:
        value = float(getattr(snapshot, "bombing_solution_age_s", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, value) if math.isfinite(value) else 0.0


def _unavailable_cue_projection(snapshot: Any) -> CCRPCueProjection:
    reason = str(getattr(snapshot, "bombing_unavailable_reason", "") or "").strip()
    if reason == "release_dynamics_unresolved":
        return CCRPCueProjection(0.42, Theme.YELLOW, "侧飞 / 转弯过大", available=False)
    if reason == "off_axis":
        return CCRPCueProjection(0.42, Theme.YELLOW, "对准目标航线", available=False)
    if reason == "terrain_unavailable":
        return CCRPCueProjection(0.42, Theme.YELLOW, "等待目标高程", available=False)
    if reason == "time_alignment_unavailable":
        return CCRPCueProjection(0.42, Theme.YELLOW, "同步 8111 时间轴", available=False)
    if reason == "release_state_unavailable":
        return CCRPCueProjection(0.42, Theme.TEXT_MUTED, "建立 8111 航迹", available=False)
    if reason in {"guided_glide", "guided_or_glide"}:
        return CCRPCueProjection(0.42, Theme.YELLOW, "当前弹药不支持 CCRP", available=False)
    if reason == "offline_high_drag_unavailable":
        return CCRPCueProjection(0.42, Theme.RED, "当前弹药模型缺失", available=False)
    if bool(getattr(snapshot, "on_ground", False)):
        return CCRPCueProjection(0.42, Theme.TEXT_MUTED, "起飞后开始解算", available=False)
    if float(getattr(snapshot, "altitude_m", 0.0) or 0.0) <= 50.0:
        return CCRPCueProjection(0.42, Theme.TEXT_MUTED, "爬升后开始解算", available=False)
    if not bool(
        getattr(snapshot, "has_bombing_target", False) or getattr(snapshot, "has_target", False)
    ):
        return CCRPCueProjection(0.42, Theme.TEXT_MUTED, "等待投弹目标", available=False)
    return CCRPCueProjection(0.42, Theme.TEXT_MUTED, "等待 CCRP 解算", available=False)


def _projection_for_release_status(status: str, time_to_release: float) -> CCRPCueProjection:
    """Project one stabilized release time onto a continuous CCRP scale."""

    if status == "passed":
        elapsed = max(0.0, time_to_release)
        crossed_gap = min(0.08, 0.006 + elapsed * 0.16)
        return CCRPCueProjection(-crossed_gap, Theme.RED, "已越过释放点")
    if status == "ready":
        ready_ratio = max(0.0, min(1.0, time_to_release / 0.5))
        release_now = time_to_release <= BallisticPhysicsParams.RELEASE_PROMPT_SEC
        status_text = "释放" if release_now else f"T−{time_to_release:.2f}s"
        return CCRPCueProjection(
            0.052 * ready_ratio,
            Theme.GREEN,
            status_text,
            pulse=release_now,
        )
    if status == "approaching":
        # The mapping is continuous with both the ready boundary at 0.5 s and
        # the far boundary at 5 s. The old piecewise mapping jumped at both.
        approach_ratio = max(0.0, min(1.0, (time_to_release - 0.5) / 4.5))
        return CCRPCueProjection(
            0.052 + 0.29 * (approach_ratio**0.82),
            Theme.YELLOW,
            f"T−{time_to_release:.1f}s",
        )
    if status == "too_far":
        far_ratio = max(0.0, min(1.0, (time_to_release - 5.0) / 20.0))
        return CCRPCueProjection(
            0.342 + 0.078 * math.sqrt(far_ratio),
            Theme.TEXT_DIM,
            f"T−{time_to_release:.0f}s",
        )
    return CCRPCueProjection(0.42, Theme.TEXT_MUTED, "等待释放航线", available=False)


def build_ccrp_cue_projection(snapshot: Any) -> CCRPCueProjection:
    """Map release timing to a symmetric cue that converges and crosses at release."""

    valid = bool(getattr(snapshot, "bombing_valid", False))
    status = str(getattr(snapshot, "release_status", "invalid") or "invalid")
    time_to_release = _finite_time_to_release(snapshot)

    if not valid or status == "invalid":
        return _unavailable_cue_projection(snapshot)
    return _projection_for_release_status(status, time_to_release)


class CCRPTimingStabilizer:
    """Track a release deadline instead of chasing noisy per-frame countdowns."""

    _DEADLINE_DEADBAND_SECONDS = 0.10
    _NEAR_DEADLINE_DEADBAND_SECONDS = 0.045
    _MAX_DEADLINE_CORRECTION_SECONDS = 0.10
    _MAX_NEAR_CORRECTION_SECONDS = 0.06
    _RESET_ERROR_SECONDS = 6.0

    def __init__(self) -> None:
        self._active = False
        self._deadline: float | None = None
        self._sample_key: tuple[str, ...] | None = None
        self._last_update: float | None = None
        self._raw_status = "invalid"
        self._fallback = CCRPCueProjection(
            0.42,
            Theme.TEXT_MUTED,
            "等待 CCRP 解算",
            available=False,
        )

    @staticmethod
    def _snapshot_key(snapshot: Any) -> tuple[str, ...]:
        return (
            str(getattr(snapshot, "bomb_name", "") or ""),
            str(getattr(snapshot, "bombing_target_mode", "") or ""),
            str(getattr(snapshot, "bombing_target_kind", "") or ""),
            str(getattr(snapshot, "bombing_target_name", "") or ""),
        )

    @property
    def active(self) -> bool:
        return self._active

    def update(self, snapshot: Any, *, now: float) -> CCRPCueProjection:
        base = build_ccrp_cue_projection(snapshot)
        if not base.available:
            self._active = False
            self._deadline = None
            self._sample_key = None
            self._last_update = now
            self._raw_status = "invalid"
            self._fallback = base
            return base

        status = str(getattr(snapshot, "release_status", "invalid") or "invalid")
        raw_time = max(0.0, _finite_time_to_release(snapshot))
        solution_age = _finite_solution_age(snapshot)
        sample_key = self._snapshot_key(snapshot)
        measured_remaining = (0.0 if status == "passed" else raw_time) - solution_age
        measured_deadline = now + measured_remaining
        previous_update = self._last_update

        if self._deadline is None or sample_key != self._sample_key:
            self._deadline = measured_deadline
        elif status == "passed":
            # The along-track geometry has already crossed. Never let a stale
            # visual deadline keep the release brackets open beyond this sample.
            self._deadline = min(self._deadline, measured_deadline)
        else:
            error = measured_deadline - self._deadline
            if abs(error) >= self._RESET_ERROR_SECONDS:
                self._deadline = measured_deadline
            else:
                near_release = raw_time <= 2.0
                deadband = (
                    self._NEAR_DEADLINE_DEADBAND_SECONDS
                    if near_release
                    else self._DEADLINE_DEADBAND_SECONDS
                )
                if abs(error) > deadband:
                    elapsed = max(0.016, now - (previous_update if previous_update is not None else now))
                    maximum = (
                        self._MAX_NEAR_CORRECTION_SECONDS
                        if near_release
                        else self._MAX_DEADLINE_CORRECTION_SECONDS
                    )
                    maximum = min(maximum, max(0.025, elapsed * 1.6))
                    gain = 0.34 if near_release else 0.22
                    self._deadline += max(-maximum, min(maximum, error * gain))

        self._active = True
        self._sample_key = sample_key
        self._last_update = now
        self._raw_status = status
        return self.projection(now=now)

    def projection(self, *, now: float) -> CCRPCueProjection:
        if not self._active or self._deadline is None:
            return self._fallback

        remaining = self._deadline - now
        if remaining <= 0.0:
            status = "passed"
        elif remaining <= 0.5:
            status = "ready"
        elif remaining <= 5.0:
            status = "approaching"
        else:
            status = "too_far"
        displayed_time = -remaining if status == "passed" else max(0.0, remaining)
        return _projection_for_release_status(status, displayed_time)


class CCRPConvergenceCue(tk.Canvas):
    """Smooth 60 Hz CCRP-style brackets driven only by a rendered UI snapshot."""

    def __init__(self, parent: tk.Misc, *, height: int, **kwargs: Any):
        super().__init__(
            parent,
            height=height,
            bg=Theme.BG,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.SEPARATOR,
            relief="flat",
            **kwargs,
        )
        self._display_gap = 0.42
        self._target_gap = 0.42
        self._projection = CCRPCueProjection(
            0.42,
            Theme.TEXT_MUTED,
            "等待 CCRP 解算",
            available=False,
        )
        self._timing = CCRPTimingStabilizer()
        self._animation_id: str | None = None
        self._pulse_phase = 0.0
        self.bind("<Configure>", lambda _event: self._draw(), add="+")

    def update_snapshot(self, snapshot: Any) -> None:
        self.set_projection(self._timing.update(snapshot, now=time.monotonic()))

    def set_projection(self, projection: CCRPCueProjection) -> None:
        self._projection = projection
        self._target_gap = max(-0.16, min(0.46, float(projection.gap_ratio)))
        if self._animation_id is None:
            self._animation_id = self.after(16, self._animate)

    def stop(self) -> None:
        if self._animation_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._animation_id)
        self._animation_id = None

    def _animate(self) -> None:
        self._animation_id = None
        if self._timing.active:
            self._projection = self._timing.projection(now=time.monotonic())
            self._target_gap = max(-0.16, min(0.46, float(self._projection.gap_ratio)))
        delta = self._target_gap - self._display_gap
        if self._target_gap <= 0.052:
            # The deadline tracker already removes sample noise and extrapolates
            # at 60 Hz. A second low-pass here used to move the visible centre
            # 0.2 s late, which is tens of metres at attack speed.
            self._display_gap = self._target_gap
        elif delta < 0.0:
            smoothing = 0.18 if abs(delta) > 0.006 else 0.28
            self._display_gap += delta * smoothing
        else:
            # Deadline corrections may move the solution slightly outward.
            # Render them more slowly than the inward release convergence.
            smoothing = 0.07 if abs(delta) > 0.006 else 0.14
            self._display_gap += delta * smoothing
        if abs(delta) < 0.0005:
            self._display_gap = self._target_gap
        if self._projection.pulse:
            self._pulse_phase = (self._pulse_phase + 0.10) % (math.tau)
        else:
            self._pulse_phase = 0.0
        self._draw()
        if (
            self._timing.active
            or abs(self._target_gap - self._display_gap) > 0.0005
            or self._projection.pulse
        ):
            self._animation_id = self.after(16, self._animate)

    def _draw(self) -> None:
        with contextlib.suppress(tk.TclError):
            self.delete("all")
            width = max(180, int(self.winfo_width() or self.winfo_reqwidth() or 320))
            height = max(34, int(self.winfo_height() or self.winfo_reqheight() or 42))
            center_x = width / 2.0
            center_y = height * 0.63
            color = self._projection.color
            gap_px = self._display_gap * width
            left_x = center_x - gap_px
            right_x = center_x + gap_px
            bracket_h = max(8.0, height * 0.24)
            foot = max(6.0, width * 0.020)
            line_width = max(2, round(height * 0.05))

            self.create_line(
                width * 0.035,
                center_y,
                width * 0.965,
                center_y,
                fill=Theme.SEPARATOR,
                width=1,
            )
            self.create_rectangle(
                center_x - 3,
                center_y - bracket_h * 0.78,
                center_x + 3,
                center_y + bracket_h * 0.78,
                outline=Theme.TEXT_DIM,
                width=1,
            )
            for x, direction in ((left_x, 1.0), (right_x, -1.0)):
                self.create_line(
                    x,
                    center_y - bracket_h,
                    x,
                    center_y + bracket_h,
                    fill=color,
                    width=line_width,
                )
                self.create_line(
                    x,
                    center_y - bracket_h,
                    x + direction * foot,
                    center_y - bracket_h,
                    fill=color,
                    width=line_width,
                )
                self.create_line(
                    x,
                    center_y + bracket_h,
                    x + direction * foot,
                    center_y + bracket_h,
                    fill=color,
                    width=line_width,
                )

            if self._projection.pulse:
                radius = 4.5 + 2.0 * (0.5 + 0.5 * math.sin(self._pulse_phase))
                self.create_oval(
                    center_x - radius,
                    center_y - radius,
                    center_x + radius,
                    center_y + radius,
                    outline=color,
                    width=2,
                )
            self.create_text(
                center_x,
                max(7, height * 0.16),
                text=self._projection.status_text,
                fill=color,
                font=("Segoe UI Semibold", max(8, int(height * 0.18))),
                anchor="center",
            )


class BombingBar:
    """Shared bombing bar controls and presentation for every host surface."""

    def __init__(
        self,
        parent: tk.Misc,
        app: Any,
        *,
        scale: float,
        standalone: bool,
        embedded: bool = False,
    ):
        self.app = app
        self.scale = max(0.6, float(scale))
        self.standalone = bool(standalone)
        self.embedded = bool(embedded)
        self.frame = tk.Frame(
            parent,
            bg=Theme.GRAYPILL,
            bd=0,
            highlightthickness=(1 if standalone or embedded else 0),
            highlightbackground=Theme.SEPARATOR,
        )
        self._build()

    def _font(self, role: str, *, size_mult: float = 1.0, min_size: int = 7):
        base = {
            "title": UIConfig.FONT_ZONE_TITLE,
            "item": UIConfig.FONT_ZONE_ITEM,
            "hint": UIConfig.FONT_HINT,
        }[role]
        relative = self.scale / max(0.01, float(self.app.scale))
        return self.app._scaled_font(base, size_mult=size_mult * relative, min_size=min_size)

    def _button(
        self,
        parent: tk.Misc,
        text: str,
        command: Any,
        *,
        variant: str = "neutral",
        padx: int | None = None,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            font=self._font("item", size_mult=0.9),
            padx=max(4, int((6 if padx is None else padx) * self.scale)),
            pady=max(1, int(1 * self.scale)),
            command=command,
            takefocus=False,
        )
        style_action_button(button, variant)
        return button

    def _build(self) -> None:
        s = self.scale
        pad_x = max(5, int(8 * s))
        pad_y = max(2, int(2 * s))

        self.header_frame = tk.Frame(self.frame, bg=Theme.GRAYPILL)
        self.header_frame.pack(fill="x", padx=pad_x, pady=(pad_y, max(1, int(1 * s))))
        self.header_frame.grid_columnconfigure(1, weight=1)
        self.title_lbl = tk.Label(
            self.header_frame,
            text="CCRP",
            font=self._font("title"),
            fg=Theme.TEXT,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        self.title_lbl.grid(row=0, column=0, sticky="w")
        self.drag_hint_lbl = None
        self._target_summary_full_text = "等待目标 · 高程 --"
        self.target_summary_lbl = tk.Label(
            self.header_frame,
            text=self._target_summary_full_text,
            font=self._font("hint", size_mult=0.90),
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
            width=1,
        )
        self.target_summary_lbl.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(int(9 * s), int(4 * s)),
        )
        self.release_lbl = tk.Label(
            self.header_frame,
            text="等待目标",
            font=self._font("title"),
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        self.release_lbl.grid(row=0, column=2, sticky="e", padx=(int(8 * s), 0))
        self.mode_btn = None
        if self.standalone:
            self.close_btn = tk.Label(
                self.header_frame,
                text="✕",
                font=self._font("title"),
                fg=Theme.TEXT_MUTED,
                bg=Theme.BG,
                cursor="hand2",
                padx=max(4, int(5 * s)),
                pady=max(1, int(1 * s)),
            )
            style_clickable_surface(self.close_btn)
            self.close_btn.bind("<Button-1>", self._return_to_integrated)
            self.close_btn.bind(
                "<Enter>",
                lambda _event: self.close_btn.configure(fg=Theme.RED, bg=Theme.BORDER),
                add="+",
            )
            self.close_btn.bind(
                "<Leave>",
                lambda _event: self.close_btn.configure(fg=Theme.TEXT_MUTED, bg=Theme.BG),
                add="+",
            )
            self.close_btn.grid(row=0, column=4, sticky="e", padx=(int(5 * s), 0))
        else:
            self.mode_btn = self._button(
                self.header_frame,
                "切换独立显示",
                self.app._toggle_bombing_mode,
                padx=7,
            )
            self.mode_btn.grid(row=0, column=3, sticky="e", padx=(int(8 * s), 0))
            self.close_btn = self._button(
                self.header_frame,
                "关闭",
                lambda: self.app._toggle_panel("show_bombing"),
                variant="danger",
                padx=8,
            )
            self.close_btn.grid(row=0, column=4, sticky="e", padx=(int(5 * s), 0))
        self.close_btn._bomana_no_drag = True
        if self.mode_btn is not None:
            self.mode_btn._bomana_no_drag = True
        self.header_frame.bind(
            "<Configure>",
            lambda _event: self._refresh_target_summary(),
            add="+",
        )
        self.target_summary_lbl.after_idle(self._refresh_target_summary)

        self.controls_frame = tk.Frame(self.frame, bg=Theme.GRAYPILL)
        self.controls_frame.pack(fill="x", padx=pad_x, pady=(0, max(1, int(2 * s))))
        self.controls_frame.grid_columnconfigure(0, weight=1)
        self.weapon_prev_btn = None
        self.weapon_next_btn = None
        self.weapon_btn = tk.Label(
            self.controls_frame,
            text="选择投弹弹药",
            font=self._font("hint", size_mult=0.9),
            fg=Theme.BLUE,
            bg=Theme.GRAYPILL,
            anchor="w",
            cursor="hand2",
            padx=max(5, int(6 * s)),
            pady=max(1, int(1 * s)),
        )
        style_clickable_surface(self.weapon_btn)
        self.weapon_btn.bind("<Button-1>", lambda _event: self.app._show_bomb_selector())
        self.weapon_btn._bomana_no_drag = True
        self.weapon_btn.grid(
            row=0,
            column=0,
            sticky="ew",
        )
        self.target_mode_btn = self._button(
            self.controls_frame,
            "目标：战区",
            self.app._toggle_bomb_target_mode,
            variant="secondary",
            padx=8,
        )
        self.target_mode_btn._bomana_no_drag = True
        self.target_mode_btn.grid(row=0, column=1, sticky="e", padx=(int(6 * s), 0))

        # Compatibility host retained but deliberately unmanaged. The target
        # summary now uses otherwise-empty space in the title row.
        self.info_frame = tk.Frame(self.frame, bg=Theme.GRAYPILL)
        self.target_altitude_lbl = tk.Label(
            self.info_frame,
            text="目标高程 --",
            font=self._font("item"),
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        self.target_altitude_lbl.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(int(8 * s), 0),
        )

        self.cue = CCRPConvergenceCue(
            self.frame,
            height=max(38, int(42 * s)),
        )
        self.cue.pack(
            fill="x",
            padx=pad_x,
            pady=(max(2, int(2 * s)), max(3, int(3 * s))),
        )

        # Compatibility-only labels retained for embedders that still inspect
        # the former fields. They are deliberately never managed: all state and
        # temporary failure guidance now lives inside the CCRP cue itself.
        self.trajectory_lbl = tk.Label(
            self.frame,
            text="目标 -- · 高精度弹道 --",
            font=self._font("item"),
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )
        self.flight_lbl = tk.Label(
            self.frame,
            text="",
            font=self._font("hint"),
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )
        self.release_detail_lbl = tk.Label(
            self.frame,
            text="进入释放航线后显示窗口",
            font=self._font("item"),
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )

    @staticmethod
    def _compact_weapon_label(text: str) -> str:
        value = str(text or "").strip()
        if not value:
            return "选择投弹弹药"
        parts = [part.strip() for part in value.split(" · ") if part.strip()]
        if parts and parts[-1] == "点击切换":
            parts.pop()
        if parts and parts[-1] == "炸弹":
            parts.pop()
        value = " · ".join(parts) or value
        if len(value) <= 30:
            return value
        return value[:27].rstrip() + "…"

    @staticmethod
    def _target_context_text(summary: str, altitude: str) -> str:
        summary_text = " ".join(str(summary or "").strip().split())
        if summary_text in {"", "--", "等待目标"}:
            summary_text = "等待目标"
        summary_text = summary_text.replace("战区 #", "战区#")
        altitude_text = " ".join(str(altitude or "").strip().split())
        altitude_text = altitude_text.replace("目标高程", "", 1).strip()
        altitude_text = altitude_text.replace(" · 等待目标", "")
        if not altitude_text:
            altitude_text = "--"
        altitude_text = f"高{altitude_text.replace(' ', '')}"
        if altitude_text != "高--" and summary_text != "等待目标":
            return f"{altitude_text}·{summary_text}"
        return f"{summary_text}·{altitude_text}"

    def _refresh_target_summary(self) -> None:
        with contextlib.suppress(tk.TclError):
            width = int(self.target_summary_lbl.winfo_width() or 0)
            if width <= 1:
                return
            set_elided_text(
                self.target_summary_lbl,
                self._target_summary_full_text,
                max(1, width - max(2, int(3 * self.scale))),
            )

    def update_snapshot(self, snapshot: Any) -> None:
        model = build_bombing_display_model(snapshot)
        self.weapon_btn.configure(text=self._compact_weapon_label(model.bomb_label_text))
        self.trajectory_lbl.configure(text=model.trajectory_text, fg=model.trajectory_fg)
        self._target_summary_full_text = self._target_context_text(
            model.target_summary_text,
            model.target_altitude_text,
        )
        self.target_summary_lbl.configure(fg=model.trajectory_fg)
        self._refresh_target_summary()
        self.target_altitude_lbl.configure(text=model.target_altitude_text or "目标高程 --")
        self.app.icons.configure_label(
            self.release_lbl,
            icon=model.release.icon,
            text=model.release.text,
            size=max(13, int(17 * self.scale)),
            fg=model.release.fg,
        )
        self.release_detail_lbl.configure(
            text=model.release_detail_text,
            fg=model.release.fg,
        )
        self.flight_lbl.configure(text=model.flight_text, fg=model.flight_fg)
        mode = BombConfig.normalize_target_mode(
            getattr(snapshot, "bombing_target_mode", BombConfig.target_mode)
        )
        mode_label = "战区" if mode == "zone" else "兴趣点"
        self.target_mode_btn.configure(
            text=f"目标：{mode_label} [{HotkeyConfig.KEY_BOMB_TARGET}]"
        )
        style_action_button(
            self.target_mode_btn,
            "success" if mode == "zone" else "warning",
        )
        self.cue.update_snapshot(snapshot)

    def _return_to_integrated(self, _event: tk.Event | None = None) -> str:
        services = getattr(self.app, "bombing_services", None)
        if services is not None:
            services.set_mode("integrated")
        elif PanelConfig.bombing_mode == "standalone":
            self.app._toggle_bombing_mode()
        return "break"

    def refresh_mode(self) -> None:
        if self.mode_btn is not None:
            self.mode_btn.configure(text="切换独立显示")

    def destroy(self) -> None:
        self.cue.stop()
        with contextlib.suppress(tk.TclError):
            self.frame.destroy()


class BombingWindow:
    """Own the separate bombing Toplevel when it is not mounted below standalone nav."""

    def __init__(self, app: Any):
        self.app = app
        self.root = app.root
        self._visible = False
        self._drag_active = False
        self._drag_data: dict[str, int] = {}
        self._transparent_color = "#010101"
        self.window = tk.Toplevel(self.root)
        self.window.title("CCRP")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg=self._transparent_color)
        self.window.withdraw()
        self.window.update_idletasks()
        internal_id = self.window.winfo_id()
        try:
            self.hwnd = ctypes.windll.user32.GetParent(internal_id) or int(internal_id)
        except _WIN32_ACCESS_ERRORS:
            self.hwnd = int(internal_id)

        scale = app.scale * PanelConfig.clamp_navigation_scale(
            PanelConfig.navigation_bar_scale
        )
        self.bar = BombingBar(
            self.window,
            app,
            scale=scale,
            standalone=True,
        )
        self.bar.frame.pack(fill="both", expand=True, padx=2, pady=2)
        self.apply_window_styles(click_through=app._locked, alpha=UIConfig.WINDOW_ALPHA)
        self._bind_drag_recursive(self.window)
        self.window.bind("<Button-3>", self._show_context_menu)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self._restore_position()

    def apply_window_styles(self, click_through: bool, alpha: int) -> None:
        try:
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(self.hwnd, -20)
            style |= 0x00080000 | 0x00000008 | 0x00000080
            if click_through:
                style |= 0x00000020 | 0x08000000
            else:
                style &= ~(0x00000020 | 0x08000000)
            user32.SetWindowLongW(self.hwnd, -20, style)
            color_hex = self._transparent_color.lstrip("#")
            r, g, b = (int(color_hex[i : i + 2], 16) for i in (0, 2, 4))
            colorref = r | (g << 8) | (b << 16)
            user32.SetLayeredWindowAttributes(
                self.hwnd,
                colorref,
                int(alpha),
                0x1 | 0x2,
            )
        except _WIN32_ACCESS_ERRORS:
            self.window.attributes("-alpha", int(alpha) / 255.0)

    def _bind_drag_recursive(self, widget: tk.Misc) -> None:
        widget.bind("<Button-1>", self._on_drag_start, add="+")
        widget.bind("<B1-Motion>", self._on_drag_motion, add="+")
        widget.bind("<ButtonRelease-1>", self._on_drag_end, add="+")
        for child in widget.winfo_children():
            self._bind_drag_recursive(child)

    def _on_drag_start(self, event: tk.Event) -> None:
        if (
            self.app._locked
            or isinstance(event.widget, (tk.Button, tk.Menubutton))
            or bool(getattr(event.widget, "_bomana_no_drag", False))
        ):
            self._drag_active = False
            return
        self._drag_active = True
        self._drag_data = {
            "x": int(event.x_root),
            "y": int(event.y_root),
            "win_x": int(self.window.winfo_x()),
            "win_y": int(self.window.winfo_y()),
        }

    def _on_drag_motion(self, event: tk.Event) -> None:
        if not self._drag_active or self.app._locked:
            return
        x = self._drag_data["win_x"] + int(event.x_root) - self._drag_data["x"]
        y = self._drag_data["win_y"] + int(event.y_root) - self._drag_data["y"]
        self.window.geometry(f"+{x}+{y}")
        PanelConfig.bombing_window_pos = (x, y)

    def _on_drag_end(self, _event: tk.Event) -> None:
        if self._drag_active:
            self.app._save_config()
        self._drag_active = False

    def _show_context_menu(self, event: tk.Event) -> None:
        menu = tk.Menu(self.window, tearoff=0)
        menu.add_command(label="重置位置", command=self._reset_position)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_close(self) -> str:
        return self.bar._return_to_integrated()

    def _reset_position(self) -> None:
        self.window.update_idletasks()
        screen_w, _screen_h = Win32.screen_size()
        x = max(0, (screen_w - self.window.winfo_reqwidth()) // 2)
        y = 80
        self.window.geometry(f"+{x}+{y}")
        PanelConfig.bombing_window_pos = (x, y)
        self.app._save_config()

    def _restore_position(self) -> None:
        position = PanelConfig.bombing_window_pos
        if position:
            try:
                x, y = int(position[0]), int(position[1])
            except (TypeError, ValueError, IndexError):
                self._reset_position()
                return
            self.window.geometry(f"+{x}+{y}")
        else:
            self._reset_position()

    def show(self) -> None:
        if self._visible:
            return
        self._visible = True
        self.window.deiconify()
        self.window.lift()
        alpha = UIConfig.WINDOW_ALPHA if self.app._locked else min(240, UIConfig.WINDOW_ALPHA + 30)
        self.apply_window_styles(click_through=self.app._locked, alpha=alpha)

    def hide(self) -> None:
        if not self._visible:
            return
        self._visible = False
        self.bar.cue.stop()
        self.window.withdraw()

    def is_visible(self) -> bool:
        return self._visible

    def update_display(self, snapshot: Any) -> None:
        if self._visible:
            self.bar.update_snapshot(snapshot)

    def destroy(self) -> None:
        self._visible = False
        self.bar.destroy()
        with contextlib.suppress(tk.TclError):
            self.window.destroy()


__all__ = [
    "BombingBar",
    "BombingWindow",
    "CCRPConvergenceCue",
    "CCRPCueProjection",
    "CCRPTimingStabilizer",
    "build_ccrp_cue_projection",
]

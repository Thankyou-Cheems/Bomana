# -*- coding: utf-8 -*-
"""Sound helpers."""

import ctypes
import queue
import threading
import time
import winsound
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from bomana.config import SoundConfig

# ============================================================================
# 音效管理
# ============================================================================

@dataclass(frozen=True)
class _SoundJob:
    pattern: str
    freq: int | None
    duration: int | None
    custom_file: str | None


class SoundManager:
    """音效管理器
    
    使用Windows Beep API播放提示音。
    在单 worker 线程播放，避免阻塞UI和高频创建线程。
    """
    _STOP = object()

    def __init__(self):
        self._lock = threading.Lock()
        self._enabled = False
        self._busy = False
        self._stopped = False
        self._queue: queue.Queue[_SoundJob | object] = queue.Queue()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="BomanaSoundWorker",
            daemon=True,
        )
        self._worker.start()
    
    def set_enabled(self, enabled: bool):
        self._enabled = enabled
    
    def is_enabled(self) -> bool:
        return self._enabled
    
    def play(
        self,
        pattern: str = "tick",
        freq: int = None,
        duration: int = None,
        *,
        force: bool = False,
        custom_file: str | None = None,
    ):
        """播放音效
        
        Args:
            pattern: 音效模式（"tick", "warning", "on", "zone_destroyed", "overspeed_warning", "overspeed_critical"）
            freq: 直接指定频率（Hz）
            duration: 直接指定持续时间（ms）
        """
        # "on"模式总是播放（用于功能开启反馈）
        if not self._enabled and not force and pattern != "on":
            return
        
        with self._lock:
            if self._stopped or self._busy:
                return
            self._busy = True

        self._queue.put(_SoundJob(pattern, freq, duration, custom_file))

    def stop(self, *, drain: bool = True, timeout: float = 1.0) -> None:
        """停止音效 worker。

        Args:
            drain: True 时等待已接收的播放任务自然结束；False 时丢弃尚未开始的任务。
            timeout: join 等待秒数，避免长音频文件阻塞退出。
        """
        with self._lock:
            if self._stopped:
                return
            self._stopped = True

        if not drain:
            self._discard_pending_jobs()

        self._queue.put(self._STOP)
        self._worker.join(timeout=max(0.0, float(timeout)))

    def close(self) -> None:
        self.stop(drain=True)

    def _discard_pending_jobs(self) -> None:
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                return
            else:
                self._queue.task_done()
                if job is self._STOP:
                    return

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is self._STOP:
                    return
                self._play_job(job)
            finally:
                if job is not self._STOP:
                    with self._lock:
                        self._busy = False
                self._queue.task_done()

    def _play_job(self, job: _SoundJob) -> None:
        try:
            if job.freq is not None and job.duration is not None:
                ctypes.windll.kernel32.Beep(int(job.freq), int(job.duration))
                return

            seq = self._get_pattern_sequence(job.pattern)
            sound_file = self._resolve_custom_sound_file(job.pattern, job.custom_file)
            if sound_file is not None:
                try:
                    self._play_audio_file(sound_file)
                    return
                except Exception:
                    pass
            self._play_sequence(seq)
        except Exception:
            pass

    @staticmethod
    def _resolve_custom_sound_file(pattern: str, custom_file: str | None = None) -> Path | None:
        candidate = str(custom_file or SoundConfig.get_custom_sound_file(pattern) or "").strip()
        if not candidate:
            return None
        path = Path(candidate)
        return path if path.exists() else None

    @staticmethod
    def _play_sequence(seq: List[Tuple[int, int, int]]) -> None:
        for (f, ms, gap) in seq:
            try:
                ctypes.windll.kernel32.Beep(int(f), int(ms))
            except Exception:
                pass
            if gap:
                time.sleep(gap / 1000.0)

    @staticmethod
    def _play_audio_file(path: Path) -> None:
        ext = path.suffix.lower()
        if ext == ".wav":
            winsound.PlaySound(str(path), winsound.SND_FILENAME)
            return
        SoundManager._play_audio_file_mci(path)

    @staticmethod
    def _play_audio_file_mci(path: Path) -> None:
        alias = f"bomana_{time.monotonic_ns()}"
        path_text = str(path).replace('"', '""')

        def _mci(command: str) -> int:
            return int(ctypes.windll.winmm.mciSendStringW(command, None, 0, None))

        err = _mci(f'open "{path_text}" alias {alias}')
        if err != 0:
            raise OSError(f"mci open failed: {err}")
        try:
            err = _mci(f"play {alias} wait")
            if err != 0:
                raise OSError(f"mci play failed: {err}")
        finally:
            _mci(f"close {alias}")
    
    @staticmethod
    def _get_pattern_sequence(pattern: str) -> List[Tuple[int, int, int]]:
        """获取音效序列
        
        Returns:
            [(频率, 持续时间, 间隔), ...]
        """
        if pattern == "on":
            return [(*SoundConfig.BEEP_ON_1, SoundConfig.ON_GAP_MS), 
                   (*SoundConfig.BEEP_ON_2, 0)]
        elif pattern == "manual_reset":
            return [(*SoundConfig.BEEP_MANUAL_RESET, 0)]
        elif pattern == "warning":
            return [(*SoundConfig.BEEP_WARNING_1, SoundConfig.WARNING_GAP_MS), 
                   (*SoundConfig.BEEP_WARNING_2, 0)]
        elif pattern == "zone_destroyed":
            return [(*SoundConfig.BEEP_ZONE_DESTROYED, 50), 
                   (*SoundConfig.BEEP_ZONE_DESTROYED, 0)]
        elif pattern == "overspeed_warning":
            return [(*SoundConfig.BEEP_OVERSPEED_WARN, 0)]
        elif pattern == "overspeed_critical":
            return [
                (*SoundConfig.BEEP_OVERSPEED_CRIT_1, SoundConfig.OVERSPEED_CRIT_GAP_MS),
                (*SoundConfig.BEEP_OVERSPEED_CRIT_2, 0),
            ]
        else:  # "tick"
            return [(*SoundConfig.BEEP_TICK, 0)]

# -*- coding: utf-8 -*-
"""Sound helpers."""

import ctypes
import threading
import time
import winsound
from pathlib import Path
from typing import List, Tuple

from bomana.config import SoundConfig

# ============================================================================
# 音效管理
# ============================================================================

class SoundManager:
    """音效管理器
    
    使用Windows Beep API播放提示音。
    在独立线程播放，避免阻塞UI。
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._enabled = False
    
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
        
        # 防止多个音效重叠
        if not self._lock.acquire(blocking=False):
            return
        
        try:
            if freq is not None and duration is not None:
                # 单音播放
                def _play_single():
                    try:
                        ctypes.windll.kernel32.Beep(int(freq), int(duration))
                    except:
                        pass
                    finally:
                        self._lock.release()
                threading.Thread(target=_play_single, daemon=True).start()
                return
            
            # 序列播放
            seq = self._get_pattern_sequence(pattern)
            sound_file = self._resolve_custom_sound_file(pattern, custom_file)

            def _play():
                try:
                    if sound_file is not None:
                        try:
                            self._play_audio_file(sound_file)
                            return
                        except Exception:
                            pass
                    self._play_sequence(seq)
                finally:
                    self._lock.release()
            threading.Thread(target=_play, daemon=True).start()
        except Exception:
            self._lock.release()
            raise

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

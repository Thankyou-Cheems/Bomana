# -*- coding: utf-8 -*-
"""Sound helpers."""

import ctypes
import threading
import time
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
    
    def play(self, pattern: str = "tick", freq: int = None, duration: int = None):
        """播放音效
        
        Args:
            pattern: 音效模式（"tick", "warning", "on", "zone_destroyed"）
            freq: 直接指定频率（Hz）
            duration: 直接指定持续时间（ms）
        """
        # "on"模式总是播放（用于功能开启反馈）
        if not self._enabled and pattern != "on":
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
            def _play():
                try:
                    for (f, ms, gap) in seq:
                        try:
                            ctypes.windll.kernel32.Beep(int(f), int(ms))
                        except:
                            pass
                        if gap:
                            time.sleep(gap / 1000.0)
                finally:
                    self._lock.release()
            threading.Thread(target=_play, daemon=True).start()
        except Exception:
            self._lock.release()
            raise
    
    @staticmethod
    def _get_pattern_sequence(pattern: str) -> List[Tuple[int, int, int]]:
        """获取音效序列
        
        Returns:
            [(频率, 持续时间, 间隔), ...]
        """
        if pattern == "on":
            return [(*SoundConfig.BEEP_ON_1, SoundConfig.ON_GAP_MS), 
                   (*SoundConfig.BEEP_ON_2, 0)]
        elif pattern == "warning":
            return [(*SoundConfig.BEEP_WARNING_1, SoundConfig.WARNING_GAP_MS), 
                   (*SoundConfig.BEEP_WARNING_2, 0)]
        elif pattern == "zone_destroyed":
            return [(*SoundConfig.BEEP_ZONE_DESTROYED, 50), 
                   (*SoundConfig.BEEP_ZONE_DESTROYED, 0)]
        else:  # "tick"
            return [(*SoundConfig.BEEP_TICK, 0)]

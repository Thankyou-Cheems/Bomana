import threading
from types import SimpleNamespace

from bomana.utils import sound
from bomana.utils.sound import SoundManager


def _mci_only_manager() -> SoundManager:
    manager = object.__new__(SoundManager)
    manager._lock = threading.Lock()
    manager._active_mci_alias = None
    manager._stopped = False
    return manager


def test_mci_playback_uses_nonblocking_play_and_status_poll(tmp_path, monkeypatch) -> None:
    commands: list[str] = []

    class FakeWinmm:
        def mciSendStringW(self, command, buffer, _buffer_size, _callback) -> int:
            commands.append(command)
            if command.startswith("status ") and buffer is not None:
                buffer.value = "stopped"
            return 0

    monkeypatch.setattr(sound.ctypes, "windll", SimpleNamespace(winmm=FakeWinmm()))
    audio = tmp_path / "alert.mp3"
    audio.write_bytes(b"fake")
    manager = _mci_only_manager()

    manager._play_audio_file_mci(audio)

    play_commands = [command for command in commands if command.startswith("play ")]
    assert play_commands
    assert all(" wait" not in command for command in play_commands)
    assert any(command.startswith("status ") for command in commands)
    assert manager._active_mci_alias is None


def test_stop_active_mci_sends_stop_and_close(monkeypatch) -> None:
    commands: list[str] = []

    class FakeWinmm:
        def mciSendStringW(self, command, _buffer, _buffer_size, _callback) -> int:
            commands.append(command)
            return 0

    monkeypatch.setattr(sound.ctypes, "windll", SimpleNamespace(winmm=FakeWinmm()))
    manager = _mci_only_manager()
    manager._active_mci_alias = "bomana_test"

    manager._stop_active_mci()

    assert commands == ["stop bomana_test", "close bomana_test"]

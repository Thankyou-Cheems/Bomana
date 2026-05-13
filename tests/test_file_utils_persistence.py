import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bomana.config import FileConfig
from bomana.utils.file_utils import ConfigManager, StateManager, atomic_write_json


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.config_file = self.tmp_path / "config.json"
        self.state_file = self.tmp_path / "state.json"
        self.config_patch = patch.object(FileConfig, "CONFIG_FILE", self.config_file)
        self.state_patch = patch.object(FileConfig, "STATE_FILE", self.state_file)
        self.config_patch.start()
        self.state_patch.start()

    def tearDown(self) -> None:
        self.state_patch.stop()
        self.config_patch.stop()
        self._tmp.cleanup()

    def test_config_load_damaged_json_does_not_overwrite_file(self) -> None:
        self.config_file.write_text("{not json", encoding="utf-8")

        self.assertEqual(ConfigManager.load(), {})
        self.assertEqual(self.config_file.read_text(encoding="utf-8"), "{not json")

    def test_config_load_non_object_json_does_not_overwrite_file(self) -> None:
        self.config_file.write_text("[1, 2, 3]", encoding="utf-8")

        self.assertEqual(ConfigManager.load(), {})
        self.assertEqual(self.config_file.read_text(encoding="utf-8"), "[1, 2, 3]")

    def test_config_migration_returns_changed_without_saving(self) -> None:
        old_config = {"config_version": 1, "panels": {}}
        self.config_file.write_text(json.dumps(old_config), encoding="utf-8")

        loaded = ConfigManager.load()

        self.assertEqual(loaded["config_version"], FileConfig.CONFIG_VERSION)
        self.assertTrue(loaded["panels"]["show_bombing"])
        self.assertIn("compile_switches", loaded)
        self.assertEqual(json.loads(self.config_file.read_text(encoding="utf-8")), old_config)

        migrated, changed = ConfigManager._migrate_config({"config_version": 1, "panels": {}})
        self.assertTrue(changed)
        self.assertEqual(migrated["config_version"], FileConfig.CONFIG_VERSION)

    def test_atomic_write_ignores_leftover_temp_file_on_load(self) -> None:
        self.config_file.write_text('{"alpha": 180}', encoding="utf-8")
        leftover = self.tmp_path / ".config.json.interrupted.tmp"
        leftover.write_text('{"alpha": 1}', encoding="utf-8")

        self.assertEqual(ConfigManager.load()["alpha"], 180)

    def test_config_save_failure_does_not_replace_original(self) -> None:
        self.config_file.write_text('{"alpha": 180}', encoding="utf-8")

        ok = ConfigManager.save({"bad": {1, 2, 3}})

        self.assertFalse(ok)
        self.assertEqual(json.loads(self.config_file.read_text(encoding="utf-8")), {"alpha": 180})
        self.assertEqual(list(self.tmp_path.glob(".config.json.*.tmp")), [])

    def test_state_save_uses_atomic_json_write(self) -> None:
        StateManager.save(
            remaining_sec=42.0,
            life_index=2,
            sortie_id=3,
            battle_signature="sig-1",
        )

        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(data["remaining_sec"], 42.0)
        self.assertEqual(data["life_index"], 2)
        self.assertEqual(data["sortie_id"], 3)
        self.assertEqual(data["battle_signature"], "sig-1")
        self.assertEqual(data["battle_signature_version"], 1)

    def test_state_load_non_object_json_does_not_clear_file(self) -> None:
        self.state_file.write_text("[1, 2, 3]", encoding="utf-8")

        self.assertIsNone(StateManager.load())
        self.assertEqual(self.state_file.read_text(encoding="utf-8"), "[1, 2, 3]")

    def test_atomic_write_json_replaces_existing_file(self) -> None:
        target = self.tmp_path / "data.json"
        target.write_text('{"old": true}', encoding="utf-8")

        atomic_write_json(target, {"new": True}, ensure_ascii=False)

        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"new": True})
        self.assertEqual(list(self.tmp_path.glob(".data.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()

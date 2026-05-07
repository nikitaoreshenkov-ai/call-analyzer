from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

import client_setup


class ClientSetupTest(unittest.TestCase):
    def test_ensure_client_template_creates_expected_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            reference_root = tmp_path / "reference"
            reference_root.mkdir(parents=True, exist_ok=True)
            default_policy_path = reference_root / "client_policy.json"
            default_policy_path.write_text(
                '{"valid_meeting_types": ["onsite", "online", "both"]}',
                encoding="utf-8",
            )

            with mock.patch.object(client_setup, "DEFAULT_POLICY_PATH", str(default_policy_path)), \
                mock.patch("client_setup.client_reference_dir", side_effect=lambda client_id: str(reference_root / client_id)), \
                mock.patch("client_setup.client_results_dir", side_effect=lambda client_id: str(tmp_path / "results" / client_id)), \
                mock.patch("client_setup.client_artifacts_dir", side_effect=lambda client_id: str(tmp_path / "artifacts" / client_id)):
                info = client_setup.ensure_client_template("Client 2")

            self.assertEqual(info["client_id"], "client_2")
            self.assertTrue((reference_root / "client_2" / "client_policy.json").exists())
            self.assertTrue((reference_root / "client_2" / "jk_names.txt").exists())
            self.assertTrue((reference_root / "client_2" / "jk_aliases.json").exists())
            self.assertTrue((reference_root / "client_2" / "expert_overrides.json").exists())
            self.assertTrue((reference_root / "client_2" / "README.md").exists())


if __name__ == "__main__":
    unittest.main()

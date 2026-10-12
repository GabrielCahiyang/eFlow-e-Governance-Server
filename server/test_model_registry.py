"""Download installation checks without network calls or real model files."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import model_registry


class ModelDownloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.models_patch = patch.object(model_registry, "MODELS_DIR", self.root)
        self.models_patch.start()
        self.addCleanup(self.models_patch.stop)
        self.content = b"GGUF-test-download"
        self.entry = model_registry.ModelEntry(
            tag="qwen3.5:2b", display_name="Test", hf_repo="test/model",
            hf_filename="upstream.gguf", chat_format=None, hf_revision="pinned",
            sha256=hashlib.sha256(self.content).hexdigest(),
        )

    def test_verified_download_uses_pinned_revision_and_standard_filename(self):
        upstream = self.root / self.entry.hf_filename
        upstream.write_bytes(self.content)
        with patch.object(model_registry, "hf_hub_download", return_value=str(upstream)) as download:
            installed = model_registry.download_model(self.entry)
        download.assert_called_once_with(
            repo_id="test/model", filename="upstream.gguf", revision="pinned",
            local_dir=str(self.root),
        )
        self.assertEqual(installed.name, "qwen3.5_2b.gguf")
        self.assertEqual(installed.read_bytes(), self.content)
        self.assertFalse(upstream.exists())

    def test_checksum_failure_preserves_existing_model_during_force_download(self):
        self.entry.local_path.write_bytes(b"existing model")
        upstream = self.root / self.entry.hf_filename
        upstream.write_bytes(b"corrupt download")
        with patch.object(model_registry, "hf_hub_download", return_value=str(upstream)):
            with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
                model_registry.download_model(self.entry, force=True)
        self.assertEqual(self.entry.local_path.read_bytes(), b"existing model")

    def test_existing_model_does_not_download_again(self):
        self.entry.local_path.write_bytes(self.content)
        with patch.object(model_registry, "hf_hub_download") as download:
            self.assertEqual(model_registry.download_model(self.entry), self.entry.local_path)
        download.assert_not_called()

    def test_http_fallback_verifies_file_before_installing(self):
        def transfer(command, **kwargs):
            output = Path(command[command.index("--output") + 1])
            output.write_bytes(self.content)

        with patch.object(model_registry.shutil, "which", return_value="curl"), \
             patch.object(model_registry.subprocess, "run", side_effect=transfer) as curl:
            installed = model_registry.download_model(self.entry, use_http=True)
        self.assertEqual(installed.read_bytes(), self.content)
        self.assertIn("/resolve/pinned/upstream.gguf?download=true", curl.call_args.args[0][-1])
        self.assertTrue(curl.call_args.kwargs["check"])


if __name__ == "__main__":
    unittest.main()

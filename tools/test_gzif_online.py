import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("gzif", Path(__file__).with_name("gzif_online.py"))
gzif = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gzif)

class InputValidationTests(unittest.TestCase):
    def test_exact_target_fingerprint(self):
        gzif.validate_inputs("", "samsung/dm3qksx/dm3q:17/CP2A.260605.016/S918NKSU8GZIF:user/release-keys")

    def test_rejects_donor_or_other_firmware(self):
        for fp in (
            "samsung/dm3qxxx/dm3q:17/CP2A.260605.016/S918BXXUAZZI8:user/release-keys",
            "samsung/dm3qksx/dm3q:16/BP4A.251205.006/S918NKSS8FZG1:user/release-keys",
            "samsung/dm3qksx/dm3q:17/CP2A.260605.016/S918NKSU8GZIF:userdebug/test-keys",
        ):
            with self.subTest(fp=fp), self.assertRaises(ValueError):
                gzif.validate_inputs("", fp)

    def test_public_asset_url(self):
        gzif.validate_inputs("https://github.com/owner/repo/releases/download/input/boot.img.lz4", "")
        gzif.validate_inputs("https://raw.githubusercontent.com/owner/repo/main/boot.img.lz4", "")

    def test_rejects_unsafe_or_non_download_urls(self):
        for url in (
            "http://github.com/o/r/releases/download/t/boot.img.lz4",
            "https://github.com.evil.example/o/r/releases/download/t/boot.img.lz4",
            "https://user:pass@github.com/o/r/releases/download/t/boot.img.lz4",
            "https://127.0.0.1/boot.img.lz4",
            "file:///etc/passwd",
            "https://github.com/o/r/blob/main/boot.img.lz4",
            "https://github.com/o/r/releases/download/t/boot.img.lz4?token=secret",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                gzif.validate_inputs(url, "")

    def test_missing_boot_input_does_not_start_port(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text('{"boot_url":"","fingerprint":""}')
            with patch.dict(os.environ, {"INPUT_BOOT_URL":"", "INPUT_FINGERPRINT":"", "GITHUB_OUTPUT":str(root/"output")}):
                inputs = gzif.resolve_inputs(config, root/"inputs.json")
            self.assertEqual(inputs["boot_url"], "")
            self.assertEqual((root/"output").read_text(), "ready=false\n")

    def test_wrong_boot_hash_rejected(self):
        from io import BytesIO
        class FakeDownload(BytesIO):
            url = "https://release-assets.githubusercontent.com/example"
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(gzif, "urlopen", return_value=FakeDownload(b"wrong firmware")):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    gzif.download_boot("https://github.com/o/r/releases/download/t/boot.img.lz4",
                                       Path(directory)/"boot.img.lz4")

if __name__ == "__main__":
    unittest.main()

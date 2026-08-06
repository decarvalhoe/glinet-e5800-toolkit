import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "sanitize-evidence.py"
SPEC = importlib.util.spec_from_file_location("sanitize_evidence", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SanitizeEvidenceTests(unittest.TestCase):
    def test_redacts_network_and_subscriber_identifiers(self):
        source = (
            "ip=192.168.8.231/24 mac=de:ad:be:ef:00:01 "
            "ipv6=2001:db8::1/64 imei=123456789012345"
        )
        result = MODULE.sanitize(source)
        self.assertNotIn("192.168.8.231", result)
        self.assertNotIn("de:ad:be:ef:00:01", result)
        self.assertNotIn("2001:db8::1", result)
        self.assertNotIn("123456789012345", result)
        self.assertIn("[IPv4]", result)
        self.assertIn("[MAC]", result)
        self.assertIn("[IPv6]", result)

    def test_preserves_time_and_pci_identifiers(self):
        source = "20:03:17 up 3:03, pci 0000:01:00.0, bus usb-xhci-hcd.3.auto-1.3"
        self.assertEqual(MODULE.sanitize(source), source)

    def test_redacts_sensitive_fields(self):
        result = MODULE.sanitize("ssid=mywifi password=hunter2 token=abcdef123")
        self.assertEqual(
            result,
            "ssid=[REDACTED] password=[REDACTED] token=[REDACTED]",
        )

    def test_redacts_quoted_json_shell_and_private_keys(self):
        source = (
            '"ssid": "Private Home WiFi", '
            "password='two words', private_key=supersecret, "
            '"authorization": "Bearer abc def"'
        )
        result = MODULE.sanitize(source)
        for secret in ("Private Home WiFi", "two words", "supersecret", "Bearer abc def"):
            self.assertNotIn(secret, result)
        self.assertEqual(result.count("[REDACTED]"), 4)

    def test_redacts_unquoted_multiword_values(self):
        authorization = ("Bear" + "er") + " " + ("SAMPLE" + "_TOKEN")
        source = (
            "ssid=Private Home WiFi mode=client\n"
            f"Authorization: {authorization}\n"
            "Authorization=Basic dXNlcjpwYXNz\n"
        )
        result = MODULE.sanitize(source)
        for secret in ("Private Home WiFi", authorization, "dXNlcjpwYXNz"):
            self.assertNotIn(secret, result)
        self.assertIn("mode=client", result)
        self.assertEqual(result.count("[REDACTED]"), 3)

    def test_sanitize_is_idempotent_for_redacted_sensitive_fields(self):
        authorization = ("Bear" + "er") + " " + ("IDEMPOTENCE" + "_TOKEN")
        source = (
            "private_key=VALUE\n"
            f"Authorization: {authorization}\n"
            "Authorization=Basic dXNlcjpwYXNz\n"
            "token=[REDACTED]\n"
        )
        once = MODULE.sanitize(source)
        twice = MODULE.sanitize(once)
        three_times = MODULE.sanitize(twice)
        self.assertEqual(once, twice)
        self.assertEqual(twice, three_times)
        for secret in ("private_key=VALUE", authorization, "dXNlcjpwYXNz"):
            self.assertNotIn(secret, once)

    def test_cli_rejects_source_as_destination(self):
        with tempfile.TemporaryDirectory(prefix="hermes-verify-sanitizer-") as tmp:
            source = Path(tmp)
            (source / "sample.txt").write_text("password=secret\n")
            before = (source / "sample.txt").read_bytes()
            result = subprocess.run(
                ["python3", str(MODULE_PATH), str(source), str(source)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((source / "sample.txt").read_bytes(), before)

    def test_cli_rejects_existing_destination_and_source_symlink(self):
        with tempfile.TemporaryDirectory(prefix="hermes-verify-sanitizer-") as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            (source / "sample.txt").write_text("password=secret\n")
            existing = subprocess.run(
                ["python3", str(MODULE_PATH), str(source), str(destination)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(existing.returncode, 0)

            destination.rmdir()
            target = root / "outside.txt"
            target.write_text("private_key=secret\n")
            (source / "linked.txt").symlink_to(target)
            linked = subprocess.run(
                ["python3", str(MODULE_PATH), str(source), str(destination)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(linked.returncode, 0)
            self.assertFalse(destination.exists())

            (source / "linked.txt").unlink()
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            through_parent = subprocess.run(
                ["python3", str(MODULE_PATH), str(source), str(linked_parent / "public")],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(through_parent.returncode, 0)
            self.assertFalse((real_parent / "public").exists())

            linked_source = root / "linked-source"
            linked_source.symlink_to(source, target_is_directory=True)
            from_linked_source = subprocess.run(
                ["python3", str(MODULE_PATH), str(linked_source), str(root / "public2")],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(from_linked_source.returncode, 0)
            self.assertFalse((root / "public2").exists())

    def test_strips_capture_trailing_whitespace_but_keeps_final_newline(self):
        self.assertEqual(MODULE.sanitize("one  \n two\t\n"), "one\n two\n")


if __name__ == "__main__":
    unittest.main()

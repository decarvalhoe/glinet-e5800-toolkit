import json
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

SHELL_FILES = [
    ROOT / "etc/init.d/gl-bluetooth",
    ROOT / "usr/bin/gl-bluetooth-run",
    ROOT / "usr/bin/gl-bt-keyboard-connect",
    ROOT / "usr/bin/gl-bluetooth-web",
    ROOT / "screenapps/screenapps",
    ROOT / "tools/health-watchdog.sh",
]

JSON_FILES = [
    ROOT / "usr/share/luci/menu.d/luci-app-gl-bluetooth.json",
    ROOT / "usr/share/rpcd/acl.d/luci-app-gl-bluetooth.json",
]

PUBLIC_FILES = SHELL_FILES + JSON_FILES + [
    ROOT / "www/luci-static/resources/view/system/bluetooth.js",
    ROOT / "docs/SESSION-20260826-SCREEN-BLUETOOTH.md",
    ROOT / "etc/bluetooth/gl-bluetooth-device.conf.example",
]


class SessionFeatureTests(unittest.TestCase):
    def test_shell_syntax(self):
        for path in SHELL_FILES:
            self.assertTrue(path.is_file(), path)
            subprocess.run(["sh", "-n", str(path)], check=True)

    def test_json_syntax(self):
        for path in JSON_FILES:
            with path.open(encoding="utf-8") as handle:
                json.load(handle)

    def test_javascript_syntax_when_node_is_available(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        subprocess.run(
            [node, "--check", str(ROOT / "www/luci-static/resources/view/system/bluetooth.js")],
            check=True,
        )

    def test_no_real_mac_is_published(self):
        # Locally administered/example all-zero MAC is allowed only in the example file.
        mac = re.compile(r"(?i)(?:[0-9a-f]{2}:){5}[0-9a-f]{2}")
        for path in PUBLIC_FILES:
            text = path.read_text(encoding="utf-8")
            matches = mac.findall(text)
            if path.name.endswith(".example"):
                self.assertEqual(matches, ["00:00:00:00:00:00"])
            else:
                self.assertEqual(matches, [], f"MAC leaked in {path}: {matches}")

    def test_luci_acl_uses_method_and_exact_command_guards(self):
        acl_path = ROOT / "usr/share/rpcd/acl.d/luci-app-gl-bluetooth.json"
        acl = json.loads(acl_path.read_text(encoding="utf-8"))["luci-app-gl-bluetooth"]
        self.assertEqual(acl["read"]["ubus"], {"file": ["exec"]})
        self.assertEqual(acl["write"]["ubus"], {"file": ["exec"]})
        commands = set(acl["read"]["file"]) | set(acl["write"]["file"])
        self.assertTrue(commands)
        self.assertNotIn("/usr/bin/gl-bluetooth-web", commands)
        self.assertTrue(all(cmd.startswith("/usr/bin/gl-bluetooth-web ") for cmd in commands))

    def test_backend_propagates_action_failures(self):
        backend = (ROOT / "usr/bin/gl-bluetooth-web").read_text(encoding="utf-8")
        self.assertIn("json_error()", backend)
        self.assertIn('/etc/init.d/gl-bluetooth start >/dev/null 2>&1 || json_error', backend)
        self.assertIn('/etc/init.d/gl-bluetooth stop >/dev/null 2>&1 || json_error', backend)
        self.assertIn('/etc/init.d/gl-bluetooth restart >/dev/null 2>&1 || json_error', backend)
        self.assertIn('/usr/bin/gl-bt-keyboard-connect >/dev/null 2>&1 || json_error', backend)
        self.assertIn('> "$FIFO" || json_error', backend)

    def test_router_script_safety_invariants(self):
        backend = (ROOT / "usr/bin/gl-bluetooth-web").read_text(encoding="utf-8")
        helper = (ROOT / "usr/bin/gl-bt-keyboard-connect").read_text(encoding="utf-8")
        screen_launcher = (ROOT / "screenapps/screenapps").read_text(encoding="utf-8")
        screen_app = (ROOT / "screenapps/app.py").read_text(encoding="utf-8")
        watchdog = (ROOT / "tools/health-watchdog.sh").read_text(encoding="utf-8")

        self.assertNotIn('. "$CONF"', backend)
        self.assertNotIn('. "$CONF"', helper)
        self.assertIn("json_escape", backend)
        self.assertNotIn("shell=True", screen_app)
        self.assertIn("STATE=$CH/tmp", screen_launcher)
        self.assertIn('> "$STATE/screenapp.mode"', screen_launcher)
        self.assertTrue(watchdog.rstrip().endswith("exit 0"))

    def test_readme_links_handoff(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("SESSION-20260826-SCREEN-BLUETOOTH.md", readme)
        self.assertTrue((ROOT / "docs/SESSION-20260826-SCREEN-BLUETOOTH.md").is_file())


if __name__ == "__main__":
    unittest.main()

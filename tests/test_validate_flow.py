import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

VALIDATE_FLOW_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "test-author"
    / "scripts"
    / "validate-flow.py"
)

_spec = importlib.util.spec_from_file_location("validate_flow", VALIDATE_FLOW_PATH)
validate_flow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate_flow)


class ValidateFlowTests(unittest.TestCase):
    def _write_flow(self, base: Path, rel: str, content: str) -> Path:
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    # --- runFlow relative path checks ---

    def test_existing_runflow_targets_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_flow(root, "_shared/_nav-home.yaml", "appId: com.example.app\n---\n- tapOn: { id: nav_home }\n")
            self._write_flow(root, "_shared/_setup-filter.yaml", "appId: com.example.app\n---\n- tapOn: { id: chip }\n")
            self._write_flow(root, "_shared/_reset-filter.yaml", "appId: com.example.app\n---\n- tapOn: { id: reset }\n")
            flow = self._write_flow(
                root,
                "01-orders/ac-01-filter-orders.yaml",
                (
                    "appId: com.example.app\n"
                    "onFlowComplete:\n"
                    "  - runFlow: ../_shared/_reset-filter.yaml\n"
                    "---\n"
                    "- launchApp:\n"
                    "    clearState: false\n"
                    "    stopApp: true\n"
                    "- runFlow: ../_shared/_nav-home.yaml\n"
                    "- runFlow:\n"
                    "    file: ../_shared/_setup-filter.yaml\n"
                    "- assertVisible:\n"
                    "    id: order_list\n"
                ),
            )
            errors, warnings = validate_flow.validate_file(flow)
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])

    def test_missing_runflow_inline_string_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flow = self._write_flow(
                root,
                "01-orders/ac-01-filter-orders.yaml",
                (
                    "appId: com.example.app\n"
                    "---\n"
                    "- launchApp:\n"
                    "    clearState: false\n"
                    "    stopApp: true\n"
                    "- runFlow: ../_shared/_missing-nav.yaml\n"
                    "- assertVisible:\n"
                    "    id: order_list\n"
                ),
            )
            errors, _ = validate_flow.validate_file(flow)
            self.assertTrue(any("Missing runFlow target '../_shared/_missing-nav.yaml'" in e for e in errors))

    def test_missing_runflow_mapping_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flow = self._write_flow(
                root,
                "01-orders/ac-01-filter-orders.yaml",
                (
                    "appId: com.example.app\n"
                    "---\n"
                    "- runFlow:\n"
                    "    file: ../_shared/_missing-setup.yaml\n"
                    "- assertVisible:\n"
                    "    id: order_list\n"
                ),
            )
            errors, _ = validate_flow.validate_file(flow)
            self.assertTrue(any("Missing runFlow target '../_shared/_missing-setup.yaml'" in e for e in errors))

    def test_optional_runflow_missing_target_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flow = self._write_flow(
                root,
                "01-orders/ac-01-filter-orders.yaml",
                (
                    "appId: com.example.app\n"
                    "---\n"
                    "- runFlow:\n"
                    "    file: ../_shared/_optional-seed.yaml\n"
                    "    optional: true\n"
                    "- assertVisible:\n"
                    "    id: order_list\n"
                ),
            )
            errors, _ = validate_flow.validate_file(flow)
            self.assertEqual(errors, [])

    def test_inline_commands_runflow_without_file_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flow = self._write_flow(
                root,
                "01-orders/ac-01-idempotent-toggle.yaml",
                (
                    "appId: com.example.app\n"
                    "---\n"
                    "- launchApp:\n"
                    "    clearState: false\n"
                    "    stopApp: true\n"
                    "- runFlow:\n"
                    "    when:\n"
                    "      notVisible:\n"
                    "        id: chip_selected\n"
                    "    commands:\n"
                    "      - tapOn:\n"
                    "          id: chip\n"
                    "- assertVisible:\n"
                    "    id: chip_selected\n"
                ),
            )
            errors, warnings = validate_flow.validate_file(flow)
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])

    # --- Account portability checks ---

    def test_hardcoded_email_and_phone_in_selectors_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flow = self._write_flow(
                root,
                "01-profile/ac-01-show-profile.yaml",
                (
                    "appId: com.example.app\n"
                    "---\n"
                    "- launchApp:\n"
                    "    clearState: false\n"
                    "    stopApp: true\n"
                    "- assertVisible:\n"
                    "    text: \"alice.qa@gmail.com\"\n"
                    "- tapOn: \"+84 912 345 678\"\n"
                ),
            )
            errors, warnings = validate_flow.validate_file(flow)
            self.assertEqual(errors, [])
            self.assertTrue(any("hardcoded email" in w for w in warnings))
            self.assertTrue(any("hardcoded phone-like literal" in w for w in warnings))

    def test_portable_patterns_env_vars_regex_and_input_text_do_not_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flow = self._write_flow(
                root,
                "01-profile/ac-01-login-and-profile.yaml",
                (
                    "appId: com.example.app\n"
                    "---\n"
                    "- launchApp:\n"
                    "    clearState: false\n"
                    "    stopApp: true\n"
                    "- tapOn:\n"
                    "    id: email_field\n"
                    "- inputText: \"qa.user@company.org\"\n"
                    "- tapOn:\n"
                    "    id: order_row\n"
                    "    index: 0\n"
                    "- copyTextFrom:\n"
                    "    id: order_code\n"
                    "    index: 0\n"
                    "- assertVisible:\n"
                    "    text: \"${maestro.copiedText}\"\n"
                    "- assertVisible:\n"
                    "    text: \".*@.*\\\\..*\"\n"
                    "- assertVisible:\n"
                    "    text: \"Order v2.10.2026\"\n"
                    "- assertVisible:\n"
                    "    text: \"${TEST_USER_EMAIL}\"\n"
                    "- assertNotVisible:\n"
                    "    text: \"sample@example.com\"\n"
                ),
            )
            errors, warnings = validate_flow.validate_file(flow)
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])

    def test_template_directory_is_exempt_from_runflow_and_portability_checks(self):
        template = (
            Path(__file__).resolve().parent.parent
            / "skills"
            / "test-author"
            / "templates"
            / "_template.yaml"
        )
        errors, warnings = validate_flow.validate_file(template)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()

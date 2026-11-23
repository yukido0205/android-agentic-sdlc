import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

SUITE_RUNNER_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "test-runner"
    / "scripts"
    / "suite-runner.py"
)

_spec = importlib.util.spec_from_file_location("suite_runner", SUITE_RUNNER_PATH)
suite_runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(suite_runner)


class ClassifyFailureTests(unittest.TestCase):
    def _classify(self, error_summary: str, debug_dir: str = "", focus_window: str = "", logcat: str = ""):
        return suite_runner.classify_failure(
            error_summary=error_summary,
            focus_window=focus_window,
            hierarchy_path="",
            logcat_path=logcat,
            app_pkg="com.example.app",
            debug_dir=debug_dir,
        )

    # --- Tier 1: Text fallback (no Maestro commands JSON) ---

    def test_assertion_with_element_hint_is_assertion_failed(self):
        err = (
            'Assertion is false: "Order #123" is visible\n'
            "Hint: Make sure the element is visible on screen and not obscured."
        )
        cause, _, _ = self._classify(err)
        self.assertEqual(cause, "ASSERTION_FAILED")

    def test_assertion_with_not_found_hint_still_prefers_assertion_failed(self):
        err = (
            'Assertion is false: "Saved" is visible\n'
            "Element not found on screen."
        )
        cause, _, _ = self._classify(err)
        self.assertEqual(cause, "ASSERTION_FAILED")

    def test_assert_that_line_is_assertion_failed(self):
        cause, _, _ = self._classify('> Assert that "Total: $10" is visible... FAILED')
        self.assertEqual(cause, "ASSERTION_FAILED")

    def test_tap_element_not_found_is_selector_not_found(self):
        err = (
            '> Tap on "Submit"... FAILED\n'
            "Element not found: Text matching regex: Submit"
        )
        cause, _, _ = self._classify(err)
        self.assertEqual(cause, "SELECTOR_NOT_FOUND")

    def test_tap_with_word_assertion_in_label_is_still_selector_not_found(self):
        err = (
            '> Tap on "View assertion details"... FAILED\n'
            "Element not found: Text matching regex: View assertion details"
        )
        cause, _, _ = self._classify(err)
        self.assertEqual(cause, "SELECTOR_NOT_FOUND")

    def test_extended_wait_timeout_is_selector_not_found(self):
        err = "Timed out waiting for element to become visible"
        cause, _, _ = self._classify(err)
        self.assertEqual(cause, "SELECTOR_NOT_FOUND")

    def test_unable_to_find_element_is_selector_not_found(self):
        err = "Unable to find element matching id: btn_save"
        cause, _, _ = self._classify(err)
        self.assertEqual(cause, "SELECTOR_NOT_FOUND")

    def test_generic_element_mention_without_not_found_defaults_to_assertion_failed(self):
        err = "Flow failed: check element state after navigation"
        cause, _, _ = self._classify(err)
        self.assertEqual(cause, "ASSERTION_FAILED")

    # --- Tier 3: Structured Maestro commands JSON ---

    def test_structured_assert_command_overrides_misleading_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = [
                {
                    "evaluatedCommand": {"tapOnElement": {"selector": {"textRegex": "Next"}}},
                    "metadata": {"status": "COMPLETED"},
                },
                {
                    "evaluatedCommand": {"assertConditionCommand": {"condition": {"visible": {"textRegex": "Done"}}}},
                    "metadata": {"status": "FAILED"},
                },
            ]
            (Path(tmp) / "commands-ac01.json").write_text(json.dumps(payload), encoding="utf-8")
            cause, evidence, _ = self._classify("Element not found: Done", debug_dir=tmp)
            self.assertEqual(cause, "ASSERTION_FAILED")
            self.assertIn("Failed Command: assertConditionCommand", evidence)

    def test_structured_tap_command_is_selector_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = [
                {
                    "command": {"tapOnElementCommand": {"selector": {"idRegex": "btn_submit"}}},
                    "metadata": {"status": "FAILED"},
                }
            ]
            (Path(tmp) / "commands-ac02.json").write_text(json.dumps(payload), encoding="utf-8")
            cause, evidence, _ = self._classify("Generic failure text", debug_dir=tmp)
            self.assertEqual(cause, "SELECTOR_NOT_FOUND")
            self.assertIn("Failed Command: tapOnElementCommand", evidence)

    def test_structured_nested_wrapper_skips_run_flow_to_leaf_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = [
                {
                    "evaluatedCommand": {"runFlowCommand": {}},
                    "metadata": {"status": "FAILED"},
                    "subCommands": [
                        {
                            "evaluatedCommand": {"assertConditionCommand": {}},
                            "metadata": {"status": "FAILED"},
                        }
                    ],
                }
            ]
            (Path(tmp) / "commands-nested.json").write_text(json.dumps(payload), encoding="utf-8")
            cause, evidence, _ = self._classify("Element not found", debug_dir=tmp)
            self.assertEqual(cause, "ASSERTION_FAILED")
            self.assertIn("Failed Command: assertConditionCommand", evidence)

    def test_structured_maestro_v2_flat_commands_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "2026-11-23_231000"
            sub.mkdir()
            payload = [
                {"type": "launchApp", "status": "SUCCESS"},
                {"type": "extendedWaitUntil", "status": "FAILED"},
            ]
            (sub / "commands.json").write_text(json.dumps(payload), encoding="utf-8")
            cause, evidence, _ = self._classify("Assertion error?", debug_dir=tmp)
            self.assertEqual(cause, "SELECTOR_NOT_FOUND")
            self.assertIn("Failed Command: extendedWaitUntil", evidence)

    def test_structured_picks_newest_commands_json_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_file = Path(tmp) / "commands-old.json"
            new_file = Path(tmp) / "commands-new.json"
            old_file.write_text(
                json.dumps([{"command": {"tapOnElementCommand": {}}, "metadata": {"status": "FAILED"}}]),
                encoding="utf-8",
            )
            new_file.write_text(
                json.dumps([{"command": {"assertConditionCommand": {}}, "metadata": {"status": "FAILED"}}]),
                encoding="utf-8",
            )
            os.utime(old_file, (1000, 1000))
            os.utime(new_file, (2000, 2000))
            cause, _, _ = self._classify("", debug_dir=tmp)
            self.assertEqual(cause, "ASSERTION_FAILED")

    def test_corrupt_commands_json_falls_back_to_text_classifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "commands-broken.json").write_text("{not valid json", encoding="utf-8")
            cause, _, _ = self._classify("Element not found: Submit", debug_dir=tmp)
            self.assertEqual(cause, "SELECTOR_NOT_FOUND")

    # --- Higher-priority causes still win ---

    def test_crash_in_logcat_wins_over_commands_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "commands-ac.json").write_text(
                json.dumps([{"command": {"tapOnElementCommand": {}}, "metadata": {"status": "FAILED"}}]),
                encoding="utf-8",
            )
            logcat = Path(tmp) / "logcat.txt"
            logcat.write_text("E/AndroidRuntime: FATAL EXCEPTION: main\n", encoding="utf-8")
            cause, _, _ = self._classify("Element not found", debug_dir=tmp, logcat=str(logcat))
            self.assertEqual(cause, "APP_CRASH_OR_ANR")

    def test_overlay_dialog_wins_over_commands_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "commands-ac.json").write_text(
                json.dumps([{"command": {"assertConditionCommand": {}}, "metadata": {"status": "FAILED"}}]),
                encoding="utf-8",
            )
            cause, _, _ = self._classify(
                "Assertion is false",
                debug_dir=tmp,
                focus_window="Window{abc u0 com.android.permissioncontroller/Dialog}",
            )
            self.assertEqual(cause, "BLOCKED_BY_OVERLAY")


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATE_SC_PATH = REPO_ROOT / "skills" / "design-state" / "scripts" / "validate-statechart.py"
TEMPLATE_PATH = REPO_ROOT / "skills" / "design-state" / "assets" / "STATECHART.template.md"

_spec = importlib.util.spec_from_file_location("validate_statechart", VALIDATE_SC_PATH)
validate_sc = importlib.util.module_from_spec(_spec)
sys.modules["validate_statechart"] = validate_sc
_spec.loader.exec_module(validate_sc)


VALID_STATECHART_MD = """# Feature Statechart

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Editing: Start
    Editing --> Submitting: Submit [isValid]
    Submitting --> Submitted: ApiSuccess
    Submitting --> Error: ApiFailure
    Error --> Submitting: Retry
    Error --> Editing: Cancel
    Submitted --> [*]
```

| State | Event / Intent | Guard | Next State | Effect / Event |
|---|---|---|---|---|
| `Idle` | `Start` | `—` | `Editing` | `loadDraft()` |
| `Editing` | `Submit` | `isValid` | `Submitting` | `submit()` |
| `Editing` | `Submit` | `!isValid` | `IGNORE` | `ShowValidationError` |
| `Submitting` | `Submit` | `—` | `IGNORE` | `—` |
| `Submitting` | `ApiSuccess` | `—` | `Submitted` | `NavigateDone` |
| `Submitting` | `ApiFailure` | `—` | `Error` | `ShowRetry` |
| `Error` | `Retry` | `—` | `Submitting` | `submit()` |
| `Error` | `Cancel` | `—` | `Editing` | `clearError()` |
| `Idle` | `ApiSuccess` | `—` | `DROP` | `—` |
| `Submitted` | `Done` | `—` | `[*]` | `—` |

**Lifecycle Recovery:** `Process death in [Editing] -> restore draft via SavedStateHandle.`
"""


class ValidateStatechartTests(unittest.TestCase):
    def _write_md(self, base: Path, name: str, content: str) -> Path:
        target = base / name
        target.write_text(content, encoding="utf-8")
        return target

    def test_template_passes_cleanly(self):
        errors, warnings, skipped = validate_sc.validate_file(TEMPLATE_PATH)
        self.assertFalse(skipped)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_valid_statechart_passes_without_errors_or_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write_md(Path(tmp), "spec.md", VALID_STATECHART_MD)
            errors, warnings, skipped = validate_sc.validate_file(p)
            self.assertFalse(skipped)
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])

    def test_composite_and_orthogonal_regions_inherit_parent_exit(self):
        md = """# Checkout

```mermaid
stateDiagram-v2
    [*] --> Active
    state Active {
        [*] --> FormReady
        FormReady --> Submitting: PlaceOrder
        Submitting --> FormError: ApiFailure
        FormError --> Submitting: Retry
        --
        [*] --> Online
        Online --> Offline: NetLost
        Offline --> Online: NetBack
    }
    Active --> [*]
```

| State | Event / Intent | Guard | Next State | Effect / Event |
|---|---|---|---|---|
| `FormReady` | `PlaceOrder` | `isOnline` | `Submitting` | `submit()` |
| `Submitting` | `PlaceOrder` | `—` | `IGNORE` | `—` |
| `Submitting` | `ApiFailure` | `—` | `FormError` | `showErr()` |
| `FormError` | `Retry` | `—` | `Submitting` | `submit()` |
| `Online` | `NetLost` | `—` | `Offline` | `showBadge()` |
| `Offline` | `NetBack` | `—` | `Online` | `hideBadge()` |
| `Active` | `Back` | `—` | `[*]` | `close()` |

**Lifecycle Recovery:** `SavedStateHandle restores form fields.`
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write_md(Path(tmp), "checkout.md", md)
            errors, warnings, _ = validate_sc.validate_file(p)
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])

    def test_missing_initial_state_is_error(self):
        md = """
```mermaid
stateDiagram-v2
    Idle --> Done: Finish
    Done --> [*]
```
| State | Event / Intent | Guard | Next State | Effect / Event |
|---|---|---|---|---|
| `Idle` | `Finish` | `—` | `Done` | `—` |

**Lifecycle Recovery:** `Config change preserved.`
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write_md(Path(tmp), "no_init.md", md)
            errors, _, _ = validate_sc.validate_file(p)
            self.assertTrue(any("[MISSING_INITIAL_STATE]" in e for e in errors))

    def test_unreachable_state_is_error(self):
        md = VALID_STATECHART_MD.replace(
            "    Submitted --> [*]",
            "    Submitted --> [*]\n    Orphan --> [*]",
        ).replace(
            "| `Submitted` | `Done` | `—` | `[*]` | `—` |",
            "| `Submitted` | `Done` | `—` | `[*]` | `—` |\n| `Orphan` | `Exit` | `—` | `[*]` | `—` |",
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write_md(Path(tmp), "orphan.md", md)
            errors, _, _ = validate_sc.validate_file(p)
            self.assertTrue(any("[UNREACHABLE_STATE]" in e and "Orphan" in e for e in errors))

    def test_dead_end_state_with_only_ignore_is_still_error(self):
        md = """
```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Stuck: Go
```
| State | Event / Intent | Guard | Next State | Effect / Event |
|---|---|---|---|---|
| `Idle` | `Go` | `—` | `Stuck` | `—` |
| `Stuck` | `Go` | `—` | `IGNORE` | `—` |

**Lifecycle Recovery:** `None needed.`
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write_md(Path(tmp), "dead_end.md", md)
            errors, _, _ = validate_sc.validate_file(p)
            self.assertTrue(any("[DEAD_END_STATE]" in e and "Stuck" in e for e in errors))

    def test_drift_between_mermaid_and_table_is_error(self):
        md = """
```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Loading: Load
    Loading --> Ready: Ok
    Ready --> [*]
```
| State | Event / Intent | Guard | Next State | Effect / Event |
|---|---|---|---|---|
| `Idle` | `Load` | `—` | `Loading` | `fetch()` |
| `Loading` | `Ok` | `—` | `PhantomState` | `—` |

**Lifecycle Recovery:** `Config change preserved.`
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write_md(Path(tmp), "drift.md", md)
            errors, _, _ = validate_sc.validate_file(p)
            self.assertTrue(any("[DRIFT_TABLE_TO_MERMAID]" in e and "PhantomState" in e for e in errors))
            self.assertTrue(any("[DRIFT_MERMAID_TO_TABLE]" in e and "Ready" in e for e in errors))

    def test_non_deterministic_transition_is_error(self):
        md = VALID_STATECHART_MD.replace(
            "| `Error` | `Cancel` | `—` | `Editing` | `clearError()` |",
            "| `Error` | `Cancel` | `—` | `Editing` | `clearError()` |\n| `Error` | `Cancel` | `—` | `Idle` | `reset()` |",
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write_md(Path(tmp), "nondet.md", md)
            errors, _, _ = validate_sc.validate_file(p)
            self.assertTrue(any("[NON_DETERMINISTIC]" in e for e in errors))

    def test_missing_table_or_missing_diagram_is_error(self):
        only_mermaid = """
```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> [*]
```
"""
        only_table = """
| State | Event / Intent | Guard | Next State | Effect / Event |
|---|---|---|---|---|
| `Idle` | `Exit` | `—` | `[*]` | `—` |
"""
        with tempfile.TemporaryDirectory() as tmp:
            p1 = self._write_md(Path(tmp), "m.md", only_mermaid)
            p2 = self._write_md(Path(tmp), "t.md", only_table)
            e1, _, _ = validate_sc.validate_file(p1)
            e2, _, _ = validate_sc.validate_file(p2)
            self.assertTrue(any("[MISSING_TABLE]" in e for e in e1))
            self.assertTrue(any("[MISSING_DIAGRAM]" in e for e in e2))

    def test_async_safety_and_lifecycle_warnings(self):
        md = """
```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Submitting: Submit
    Submitting --> Done: Success
    Done --> [*]
```
| State | Event / Intent | Guard | Next State | Effect / Event |
|---|---|---|---|---|
| `Idle` | `Submit` | `—` | `Submitting` | `callApi()` |
| `Submitting` | `Success` | `—` | `Done` | `close()` |
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write_md(Path(tmp), "async_warn.md", md)
            errors, warnings, _ = validate_sc.validate_file(p)
            self.assertEqual(errors, [])
            self.assertTrue(any("[ASYNC_MISSING_ERROR_OR_CANCEL]" in w for w in warnings))
            self.assertTrue(any("[ASYNC_MISSING_REENTRY_GUARD]" in w for w in warnings))
            self.assertTrue(any("[MISSING_LIFECYCLE_RECOVERY]" in w for w in warnings))

    def test_cognitive_budget_warning_over_12_states(self):
        states = [f"S{i}" for i in range(13)]
        edges = "\n".join(f"    {states[i]} --> {states[i+1]}: Next" for i in range(12))
        rows = "\n".join(
            f"| `{states[i]}` | `Next` | `—` | `{states[i+1]}` | `—` |" for i in range(12)
        )
        md = f"""
```mermaid
stateDiagram-v2
    [*] --> S0
{edges}
    S12 --> [*]
```
| State | Event / Intent | Guard | Next State | Effect / Event |
|---|---|---|---|---|
{rows}
| `S12` | `Finish` | `—` | `[*]` | `—` |

**Lifecycle Recovery:** `SavedStateHandle restores step.`
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write_md(Path(tmp), "big.md", md)
            errors, warnings, _ = validate_sc.validate_file(p)
            self.assertEqual(errors, [])
            self.assertTrue(any("[COGNITIVE_BUDGET]" in w for w in warnings))

    def test_skipped_marker_passes_single_file_check(self):
        md = "# Task\n\nStatechart: SKIPPED (trivial read-only screen)\n"
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write_md(Path(tmp), "skip.md", md)
            errors, warnings, skipped = validate_sc.validate_file(p)
            self.assertTrue(skipped)
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])

    def test_cli_json_output_and_exit_codes(self):
        proc = subprocess.run(
            [sys.executable, str(VALIDATE_SC_PATH), str(TEMPLATE_PATH), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["errors"], 0)
        self.assertEqual(payload["validated_files"], 1)


if __name__ == "__main__":
    unittest.main()

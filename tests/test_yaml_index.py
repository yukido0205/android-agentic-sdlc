import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
YAML_INDEX_PATH = REPO_ROOT / "skills" / "test-author" / "scripts" / "yaml_index.py"
VALIDATE_FLOW_PATH = REPO_ROOT / "skills" / "test-author" / "scripts" / "validate-flow.py"
SUITE_RUNNER_PATH = REPO_ROOT / "skills" / "test-runner" / "scripts" / "suite-runner.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


yaml_index = _load_module("yaml_index", YAML_INDEX_PATH)
validate_flow = _load_module("validate_flow_fm", VALIDATE_FLOW_PATH)
suite_runner = _load_module("suite_runner_fm", SUITE_RUNNER_PATH)


class YamlIndexAndManifestTests(unittest.TestCase):
    def _write(self, root: Path, rel: str, content: str) -> Path:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_four_tier_feature_inference_and_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            maestro = root / ".maestro"
            self._write(
                maestro,
                "feature-map.json",
                json.dumps(
                    {
                        "version": 1,
                        "features": {
                            "checkout-payment": {
                                "description": "Promo code and payment submission.",
                                "instruction": "Needs 1 item in cart.",
                                "keywords": ["voucher", "payment"],
                                "code_paths": ["feature/checkout/", "ui/legacy/Step2Sheet.kt"],
                                "nav": ".maestro/_shared/_nav-checkout.yaml",
                            },
                            "profile-settings": {
                                "description": "Account profile preferences.",
                                "keywords": ["avatar", "bio"],
                                "code_paths": ["feature/profile/"],
                                "nav": ".maestro/_shared/_nav-profile.yaml",
                            },
                        },
                    }
                ),
            )
            # Tier 1: Explicit # Feature header overrides folder name
            self._write(
                maestro,
                "PROJ-10/regression/r-01-voucher-expired.yaml",
                "# Feature: checkout-payment\nappId: com.example.app\nname: \"Expired voucher\"\n---\n- assertVisible: { id: err }\n",
            )
            # Tier 2: Semantic folder name NN-<domain>
            self._write(
                maestro,
                "PROJ-11/01-order-list/ac-01-list-orders.yaml",
                "appId: com.example.app\nname: \"Display order list\"\n---\n- assertVisible: { id: list }\n",
            )
            # Tier 3a: Nav helper match inside legacy cryptic folder s3
            self._write(
                maestro,
                "PROJ-02/s3/ac-01-pay.yaml",
                "appId: com.example.app\nname: \"Pay now\"\n---\n- runFlow: ../../_shared/_nav-checkout.yaml\n- assertVisible: { id: btn_pay }\n",
            )
            # Tier 3b: Keyword match inside cryptic folder f2
            self._write(
                maestro,
                "PROJ-03/f2/ac-01-edit-bio.yaml",
                "appId: com.example.app\nname: \"Update avatar and bio\"\n---\n- assertVisible: { id: saved }\n",
            )
            # Tier 4: Truly unmapped legacy file (must NOT become feature 's9')
            self._write(
                maestro,
                "PROJ-01/s9/legacy-special-flow.yaml",
                "appId: com.example.app\nname: \"Verify deep notification badge\"\n---\n- assertVisible: { id: badge }\n",
            )
            # Helper files must be ignored
            self._write(maestro, "_shared/_nav-checkout.yaml", "appId: com.example.app\n---\n- tapOn: { id: tab }\n")

            fmap = yaml_index.load_feature_map(maestro)
            flows = yaml_index.scan_flows(maestro, fmap)
            by_name = {Path(f["path"]).name: f for f in flows}

            self.assertEqual(len(flows), 5)
            self.assertEqual(by_name["r-01-voucher-expired.yaml"]["feature"], "checkout-payment")
            self.assertEqual(by_name["r-01-voucher-expired.yaml"]["feature_source"], "header")
            self.assertEqual(by_name["ac-01-list-orders.yaml"]["feature"], "order-list")
            self.assertEqual(by_name["ac-01-list-orders.yaml"]["feature_source"], "folder")
            self.assertEqual(by_name["ac-01-pay.yaml"]["feature"], "checkout-payment")
            self.assertEqual(by_name["ac-01-pay.yaml"]["feature_source"], "nav-match")
            self.assertEqual(by_name["ac-01-edit-bio.yaml"]["feature"], "profile-settings")
            self.assertEqual(by_name["ac-01-edit-bio.yaml"]["feature_source"], "keyword-match")
            self.assertEqual(by_name["legacy-special-flow.yaml"]["feature"], "unmapped")

            # Lookup by cryptic dev filename matches via feature-map code_paths
            m_feats, m_flows = yaml_index.match_flows(flows, fmap, files=["app/src/main/ui/legacy/Step2Sheet.kt"])
            self.assertIn("checkout-payment", m_feats)
            matched_names = {Path(f["path"]).name for f in m_flows}
            self.assertIn("r-01-voucher-expired.yaml", matched_names)
            self.assertIn("ac-01-pay.yaml", matched_names)

            # Free-text query still discovers unmapped legacy flows
            _, q_flows = yaml_index.match_flows(flows, fmap, query="notification badge")
            self.assertEqual([Path(f["path"]).name for f in q_flows], ["legacy-special-flow.yaml"])

            # Coverage includes feature-map features, folder-inferred features, and unmapped bucket
            cov = {r["feature"]: r for r in yaml_index.build_coverage(flows, fmap)}
            self.assertEqual(cov["checkout-payment"]["count"], 2)
            self.assertEqual(cov["order-list"]["count"], 1)
            self.assertEqual(cov["profile-settings"]["count"], 1)
            self.assertEqual(cov["unmapped"]["count"], 1)

    def test_works_without_feature_map_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            maestro = Path(tmp) / ".maestro"
            self._write(
                maestro,
                "PROJ-50/02-cart-items/ac-01-add-item.yaml",
                "appId: com.example.app\nname: \"Add item to cart\"\n---\n- assertVisible: { id: cart_count }\n",
            )
            fmap = yaml_index.load_feature_map(maestro)
            self.assertEqual(fmap, {})
            flows = yaml_index.scan_flows(maestro, fmap)
            self.assertEqual(len(flows), 1)
            self.assertEqual(flows[0]["feature"], "cart-items")

            # Token fallback matches source file without feature-map.json
            _, matched = yaml_index.match_flows(flows, fmap, files=["feature/cart/CartItemsViewModel.kt"])
            self.assertEqual(len(matched), 1)

    def test_manifest_generation_and_suite_runner_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            maestro = root / ".maestro"
            f1 = self._write(
                maestro,
                "PROJ-100/03-checkout/ac-01-apply-voucher.yaml",
                "appId: com.example.app\nname: \"AC-01 Apply voucher\"\n---\n- assertVisible: { id: total }\n",
            )
            f2 = self._write(
                maestro,
                "PROJ-245/03-checkout/ac-01-repro.yaml",
                "appId: com.example.app\nname: \"AC-01 Expired voucher crash\"\n---\n- assertVisible: { id: err }\n",
            )
            manifest = root / "plans" / "PROJ-245" / "regression.flows"
            yaml_index.write_manifest(
                manifest,
                [{"path": str(f1)}, {"path": str(f2)}, {"path": str(f1)}],
                source_desc="unit-test",
            )

            # suite-runner find_flows reads .flows manifest & deduplicates
            loaded = suite_runner.find_flows(str(manifest))
            self.assertEqual(len(loaded), 2)
            self.assertEqual({Path(x["path"]).name for x in loaded}, {"ac-01-apply-voucher.yaml", "ac-01-repro.yaml"})

            # Smart target resolution: plans/PROJ-245/flow-bug.md -m regression -> plans/PROJ-245/regression.flows
            self._write(root, "plans/PROJ-245/flow-bug.md", "# PROJ-245\n")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SUITE_RUNNER_PATH),
                    "plans/PROJ-245/flow-bug.md",
                    "-m",
                    "regression",
                    "--dry-run",
                ],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("cross-ticket regression manifest: plans/PROJ-245/regression.flows", proc.stdout)
            self.assertIn("Discovered 2 flows", proc.stdout)

    def test_validate_feature_map_json(self):
        # Template itself passes with 0 errors and 0 warnings
        tpl = REPO_ROOT / "skills" / "test-author" / "templates" / "feature-map.json"
        errs, warns = validate_flow.validate_feature_map_json(tpl)
        self.assertEqual(errs, [])
        self.assertEqual(warns, [])

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "feature-map.json"
            bad.write_text(
                json.dumps(
                    {
                        "features": {
                            "checkout": {
                                "description": 123,
                                "keywords": "not-a-list",
                                "nav": ".maestro/_shared/_missing.yaml",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            errs, warns = validate_flow.validate_feature_map_json(bad)
            self.assertEqual(len(errs), 2)
            self.assertEqual(len(warns), 1)


if __name__ == "__main__":
    unittest.main()

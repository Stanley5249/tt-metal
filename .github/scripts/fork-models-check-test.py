#!/usr/bin/env python3
"""Run fork-models-check.py against fake installed trees of the stable and
nightly models/ layouts, with no wheel or tt-metal dependencies."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECK = Path(__file__).resolve().parent / "fork-models-check.py"
MODULES = ("generator", "generator_vllm", "model_config")
PARAMS = "model_params/Llama-3.2-1B-Instruct/config.json"

# A reduced copy of upstream's models/tt_transformers/__init__.py since
# v0.82.0-dev20261101: old names import the module objects of the new ones.
ALIAS = """
import importlib, importlib.abc, importlib.util, sys

__path__ = []


class _Alias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def _target(self, name):
        return "models.ttt_compat" + name[len(__name__):]

    def find_spec(self, name, path=None, target=None):
        if not name.startswith(__name__ + "."):
            return None
        try:
            if importlib.util.find_spec(self._target(name)) is None:
                return None
        except ModuleNotFoundError:
            return None
        return importlib.util.spec_from_loader(name, self)

    def create_module(self, spec):
        return importlib.import_module(self._target(spec.name))

    def exec_module(self, module):
        pass


sys.meta_path.insert(0, _Alias())
"""


def write(root, rel, text=""):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def implementation(root, package, modules=MODULES, params=True):
    """Write the tt/ modules and model parameters of models/<package>."""
    for module in modules:
        write(root, f"models/{package}/tt/{module}.py", "raise SystemExit('module ran')\n")
    if params:
        write(root, f"models/{package}/{PARAMS}", "{}")


class ModelsCheckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.site = Path(tmp.name, "site")
        self.checkout = Path(tmp.name, "checkout")

    def run_check(self, *path):
        """Run the check with `path` before the site on PYTHONPATH."""
        env = os.environ | {"PYTHONPATH": os.pathsep.join(map(str, (*path, self.site)))}
        return subprocess.run([sys.executable, CHECK, "--site", self.site], env=env, capture_output=True, text=True)

    def assert_fails(self, result, message):
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(message, result.stderr)

    def test_stable_layout(self):
        implementation(self.site, "tt_transformers")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("models/tt_transformers/tt/model_config.py", result.stdout)

    def test_nightly_layout_follows_alias(self):
        write(self.site, "models/tt_transformers/__init__.py", ALIAS)
        implementation(self.site, "ttt_compat")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("models/ttt_compat/tt/generator_vllm.py", result.stdout)

    def test_alias_without_implementation(self):
        write(self.site, "models/tt_transformers/__init__.py", ALIAS)
        self.assert_fails(self.run_check(), "models.tt_transformers.tt.generator is missing")

    def test_missing_module(self):
        write(self.site, "models/tt_transformers/__init__.py", ALIAS)
        implementation(self.site, "ttt_compat", modules=("generator", "model_config"))
        self.assert_fails(self.run_check(), "models.tt_transformers.tt.generator_vllm is missing")

    def test_missing_params(self):
        write(self.site, "models/tt_transformers/__init__.py", ALIAS)
        implementation(self.site, "ttt_compat", params=False)
        self.assert_fails(self.run_check(), f"ttt_compat/{PARAMS} is missing")

    def test_checkout_shadows_wheel(self):
        implementation(self.site, "tt_transformers")
        implementation(self.checkout, "tt_transformers")
        self.assert_fails(self.run_check(self.checkout), "not the installed wheel")


if __name__ == "__main__":
    unittest.main()

"""Load `config.py` by its path, never through `sys.path`.

`importlib.reload(config)` fails with

    ModuleNotFoundError: spec not found for the module 'config'

as soon as the repository root is not on `sys.path` at call time — which
happens in the QGIS console when the project is saved outside the repository,
or when the script is started with `exec()` rather than with the console's
"open script" button, the only thing that defines `__file__`.

The trap is insidious for two reasons:

  * `import config` still succeeds, served by the `sys.modules` cache of a
    previous run — so on the OLD region, silently;
  * the preceding `reload(analysis_shape.X)` calls pass without error, since a
    submodule reloads from its package's `__path__` without looking at
    `sys.path`. Only a top-level module fails.

This module lives in `analysis_shape/` precisely for that: its own `__file__`
reliably gives the repository root, whatever the console did, and lets it
repair `sys.path` on the way.
"""

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config():
    """The repository's `config` module, re-read from disk on every call.

    Replaces `import config; importlib.reload(config)`: same intent — never
    reuse a stale `REGION` — but without depending on the state of `sys.path`
    or `sys.modules`.
    """
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

    path = os.path.join(ROOT, "config.py")
    spec = importlib.util.spec_from_file_location("config", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"config.py not found at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # `from config import …` elsewhere in the chain must see the same fresh
    # version, not the one the cache kept from the previous run.
    sys.modules["config"] = module
    return module

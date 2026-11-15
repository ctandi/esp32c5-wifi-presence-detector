"""Install what Home Assistant's Bluetooth integration needs, for the tests.

`pip install pytest-homeassistant-custom-component` brings Home Assistant itself but
not the requirements of its integrations (usb, bluetooth, hassio, ...), because Home
Assistant normally installs those at run time. The integration under test depends on
`bluetooth_adapters`, so this reads the requirements from the manifests of the
*installed* Home Assistant, for that integration and everything it depends on, and
installs them. It follows whatever version is installed, so nothing needs updating.

    python test/ha/install_requirements.py
"""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOTS = ["bluetooth_adapters", "bluetooth", "usb"]


def main() -> None:
    spec = importlib.util.find_spec("homeassistant")
    if spec is None or not spec.submodule_search_locations:
        sys.exit("homeassistant is not installed: pip install pytest-homeassistant-custom-component")
    components = Path(list(spec.submodule_search_locations)[0]) / "components"

    seen: set[str] = set()
    requirements: set[str] = set()
    todo = list(ROOTS)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        manifest_file = components / name / "manifest.json"
        if not manifest_file.exists():
            continue
        manifest = json.loads(manifest_file.read_text())
        requirements.update(manifest.get("requirements", []))
        todo.extend(manifest.get("dependencies", []))
        todo.extend(manifest.get("after_dependencies", []))

    print(f"{len(seen)} integrations, {len(requirements)} requirements")
    if requirements:
        subprocess.run([sys.executable, "-m", "pip", "install", *sorted(requirements)], check=True)


if __name__ == "__main__":
    main()

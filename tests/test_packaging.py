import json
from pathlib import Path


def test_runtime_bundle_and_release_metadata_are_self_contained():
    root = Path(__file__).resolve().parents[1]
    component = root / "custom_components" / "ha_tgen"
    manifest = json.loads((component / "manifest.json").read_text())
    package = json.loads((root / "package.json").read_text())
    hacs = json.loads((root / "hacs.json").read_text())
    assert manifest["version"] == package["version"] == "0.1.0"
    assert manifest["config_flow"] and manifest["single_config_entry"]
    assert hacs["homeassistant"] == "2026.9.0"
    assert (component / "frontend" / "panel.js").is_file()
    assert (component / "brand" / "icon.png").is_file()
    assert not (component / "frontend" / "demo.html").exists()
    assert json.loads((component / "translations" / "en.json").read_text()) == json.loads((component / "strings.json").read_text())

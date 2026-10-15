from pathlib import Path
import importlib.util

import pytest

spec = importlib.util.spec_from_file_location("release_version", Path(__file__).resolve().parents[1] / "scripts/release_version.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("base_code, expected_code", [(3, 100009), (100100, 100109)])
def test_ci_version_upgrades_local_and_previous_published_apks(tmp_path, base_code, expected_code):
    project = tmp_path / "windows/pyproject.toml"
    project.parent.mkdir()
    project.write_text('[project]\nversion = "0.4.0"\n', encoding="utf-8")
    (tmp_path / "windows/devicedrop").mkdir()
    gradle = tmp_path / "android/app/build.gradle.kts"
    gradle.parent.mkdir(parents=True)
    gradle.write_text(f'versionCode = {base_code}\nversionName = "0.4.0"\n', encoding="utf-8")
    assert module.stamp(tmp_path, 9) == "0.4.9"
    assert f"versionCode = {expected_code}" in gradle.read_text(encoding="utf-8")
    assert 'versionName = "0.4.9"' in gradle.read_text(encoding="utf-8")
    assert '__version__ = "0.4.9"' in (tmp_path / "windows/devicedrop/__init__.py").read_text(encoding="utf-8")
    assert 'version = "0.4.9"' in project.read_text(encoding="utf-8")


def test_ci_version_requires_positive_run_number(tmp_path):
    with pytest.raises(ValueError):
        module.stamp(tmp_path, 0)

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from devicedrop import packages
from devicedrop.ui.main_window import MainWindow


def apk_assets(tmp_path, data=b"APK test bytes"):
    assets = tmp_path / "assets"
    folder = assets / "android"
    folder.mkdir(parents=True)
    (folder / "FileFastFlow.apk").write_bytes(data)
    (folder / "manifest.json").write_text(json.dumps({"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}))
    return assets


def test_apk_export_and_hash_checked_before_replace(tmp_path):
    assets = apk_assets(tmp_path)
    output = tmp_path / "Android package.apk"
    progress = []
    assert packages.create_package("android", output, assets=assets, progress=progress.append) == output
    assert output.read_bytes() == b"APK test bytes" and progress[-1] == 100
    (assets / "android" / "FileFastFlow.apk").write_bytes(b"damaged")
    with pytest.raises(ValueError, match="dañado"):
        packages.create_package("android", output, assets=assets)
    assert output.read_bytes() == b"APK test bytes"
    assert not list(tmp_path.glob(".devicedrop-package-*"))


def test_reject_output_inside_app_and_missing_apk(tmp_path):
    assets = apk_assets(tmp_path)
    bundle = tmp_path / "application"
    bundle.mkdir()
    with pytest.raises(ValueError, match="fuera"):
        packages.create_package("windows", bundle / "setup.exe", assets=assets, bundle=bundle)
    with pytest.raises(ValueError, match="fuera"):
        packages.create_package("android", assets / "copy.apk", assets=assets)
    with pytest.raises(ValueError, match="APK incluido"):
        packages.create_package("android", tmp_path / "copy.apk", assets=tmp_path / "missing")


def test_compiler_failure_preserves_destination_and_handles_spaces(tmp_path, monkeypatch):
    assets = tmp_path / "assets with spaces"
    compiler = assets / "inno" / "ISCC.exe"
    compiler.parent.mkdir(parents=True); compiler.write_bytes(b"compiler")
    (assets / "FileFastFlow.iss").write_text("recipe")
    bundle = tmp_path / "app with spaces"
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "FileFastFlow.exe").write_bytes(b"app")
    output = tmp_path / "setup with spaces.exe"
    output.write_bytes(b"old installer")
    commands = []
    def fail(command, **kwargs):
        commands.append(command)
        kwargs["stdout"].write(b"Compile error")
        return SimpleNamespace(returncode=2)
    monkeypatch.setattr(packages.subprocess, "run", fail)
    with pytest.raises(ValueError, match="Compile error"):
        packages.create_package("windows", output, assets=assets, bundle=bundle)
    assert f"/DAppSource={bundle}" in commands[0]
    assert output.read_bytes() == b"old installer"
    assert not list(tmp_path.glob(".devicedrop-package-*"))


def test_buttons_worker_export_cancel_and_error_recovery(runtime, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(runtime)
    assets = apk_assets(tmp_path)
    monkeypatch.setattr(packages, "assets_dir", lambda: assets)
    output = tmp_path / "export.apk"
    selections = iter([("", ""), (str(output), ""), (str(tmp_path / "failed.apk"), "")])
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: next(selections))
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[-1]))
    try:
        assert window.nav.item(5).text() == "Instaladores"
        window.android_package_button.click()
        assert window.package_worker is None
        window.android_package_button.click()
        assert not window.windows_package_button.isEnabled() and not window.android_package_button.isEnabled()
        worker = window.package_worker
        assert worker.wait(5000)
        app.processEvents()
        assert window.last_package == output and output.read_bytes() == b"APK test bytes"
        assert window.android_package_button.isEnabled() and window.package_worker is None
        (assets / "android" / "FileFastFlow.apk").write_bytes(b"broken")
        window.android_package_button.click()
        worker = window.package_worker
        assert worker.wait(5000)
        app.processEvents()
        assert errors and not (tmp_path / "failed.apk").exists()
        assert window.windows_package_button.isEnabled() and window.package_worker is None
    finally:
        if window.package_worker:
            window.package_worker.wait(5000); app.processEvents()
        window.timer.stop(); window.tray.hide(); runtime.bus.listeners.clear(); window.deleteLater(); app.processEvents()

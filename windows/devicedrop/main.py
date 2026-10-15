import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="FileFastFlow LAN")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--smoke-test", action="store_true", help="Open UI, verify server and exit after 3 seconds")
    parser.add_argument("--package-smoke-test", action="store_true", help="Verify both offline package buttons and exit")
    parser.add_argument("--notification-url", help="Handle a received-file notification")
    args = parser.parse_args()
    args.notification = None
    if args.notification_url:
        from devicedrop.ui.receipt_notifications import parse_notification_url
        try:
            args.notification = parse_notification_url(args.notification_url)
        except ValueError as error:
            parser.error(str(error))
        if args.headless:
            parser.error("Una notificación requiere la aplicación de escritorio.")
    from devicedrop.runtime import Runtime
    if args.headless:
        runtime = Runtime(args.data_dir, args.port)
        runtime.start(); runtime.ready.wait(10)
        try:
            if runtime.start_error:
                raise RuntimeError(runtime.start_error)
            while not runtime.stopped.wait(1):
                pass
        except KeyboardInterrupt:
            pass
        finally:
            runtime.stop()
        return
    from PySide6.QtWidgets import QApplication, QMessageBox
    from devicedrop.instance import SingleInstance
    app = QApplication(sys.argv); app.setApplicationName("FileFastFlow"); app.setQuitOnLastWindowClosed(False)
    instance = SingleInstance(Runtime.data_root(args.data_dir), app)
    try:
        if not instance.start_or_activate(notification=args.notification):
            return 0
        # Acquire the instance before opening SQLite or touching received files.
        runtime = Runtime(args.data_dir, args.port)
        return run_desktop(args, app, runtime, instance)
    except RuntimeError as error:
        QMessageBox.critical(None, "FileFastFlow", str(error))
        return 1
    finally:
        instance.close()


def run_desktop(args, app, runtime, instance):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QFormLayout, QLineEdit, QPushButton, QFileDialog
    from devicedrop.ui.main_window import MainWindow
    from devicedrop.window_activation import restore_application_window
    main_window = [None]
    def activate():
        restore_application_window(main_window[0], app)
    instance.activated.connect(activate)
    instance.notification_requested.connect(lambda action, tid: main_window[0].handle_receipt_action(action, tid) if main_window[0] else None)
    if not runtime.db.setting("onboarded") and not (args.smoke_test or args.package_smoke_test):
        dialog = QDialog(); dialog.setWindowTitle("Bienvenido a FileFastFlow"); layout = QFormLayout(dialog)
        name = QLineEdit(runtime.db.setting("device_name")); folder = QLineEdit(runtime.db.setting("receive_folder")); layout.addRow("Nombre de este dispositivo", name); layout.addRow("Carpeta recepción", folder)
        choose = QPushButton("Elegir carpeta")
        def choose_folder():
            selected = QFileDialog.getExistingDirectory(dialog, "Carpeta recibidos", folder.text())
            if selected:
                folder.setText(selected)
        choose.clicked.connect(choose_folder); layout.addRow(choose)
        next_button = QPushButton("Continuar")
        def proceed():
            if name.text().strip() and len(name.text().strip()) <= 80 and folder.text().strip():
                try:
                    path = Path(folder.text()).resolve(); path.mkdir(parents=True, exist_ok=True)
                except OSError:
                    return
                runtime.db.set_setting("device_name", name.text().strip()); runtime.configure_reception_folder(path); runtime.db.set_setting("onboarded", True); dialog.accept()
        next_button.clicked.connect(proceed); layout.addRow(next_button)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            runtime.db.close(); return
    window = MainWindow(runtime)
    main_window[0] = window
    if runtime.db.setting("start_windows") and not (args.smoke_test or args.package_smoke_test):
        try:
            window.configure_startup(True)
        except OSError:
            runtime.logger.warning("startup_registration_failed")
    if not args.notification or args.notification[0] != "copy":
        window.restore_window()
    runtime.start()
    if args.notification:
        QTimer.singleShot(0, lambda: window.handle_receipt_action(*args.notification))
    if args.package_smoke_test:
        import json
        window.nav.setCurrentRow(window.SOFTWARE_PAGE)
        kinds = iter(["windows", "android"])
        results = []
        def package_result(success, message):
            results.append({"success": success, "result": message})
        def next_package():
            kind = next(kinds, None)
            if kind is None:
                ok = len(results) == 2 and all(item["success"] for item in results)
                window.grab().save(str(runtime.root / "installers-smoke.png"))
                (runtime.root / "package_smoke_result.json").write_text(json.dumps({"success": ok, "packages": results}), encoding="utf-8")
                window.quit(); app.exit(0 if ok else 1)
                return
            from devicedrop.packages import default_filename
            window.generate_package(kind, runtime.root / default_filename(kind))
            window.package_worker.completed.connect(package_result)
            window.package_worker.finished.connect(lambda: QTimer.singleShot(0, next_package))
        QTimer.singleShot(500, next_package)
    elif args.smoke_test:
        def verify():
            import json
            ok = runtime.server is not None and runtime.server.started and not runtime.start_error
            window.grab().save(str(runtime.root / "windows-smoke.png"))
            (runtime.root / "smoke_result.json").write_text(json.dumps({"ui_started": window.isVisible(), "server_started": ok}), encoding="utf-8")
            print("WINDOWS_SMOKE_OK" if ok else "WINDOWS_SMOKE_FAILED", flush=True)
            window.quit()
            app.exit(0 if ok else 1)
        QTimer.singleShot(3500, verify)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main() or 0)

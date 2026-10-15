from pathlib import Path
from uuid import uuid4

import pytest

from devicedrop.storage.spaces import FileSpaces


def test_spaces_preserve_files_across_instances_and_duplicate_names(tmp_path):
    spaces = FileSpaces(tmp_path / "data")
    source = tmp_path / "photo.txt"; source.write_text("first")
    original = spaces.store([source])[0]
    source.write_text("second")
    duplicate = spaces.store([source])[0]
    reloaded = FileSpaces(tmp_path / "data")
    assert reloaded.files() == [duplicate, original]
    assert original.read_text() == "first" and duplicate.read_text() == "second"
    assert spaces.store([original]) == [original]
    private = spaces.store([source], str(uuid4()))[0]
    assert private.parent != original.parent


def test_failed_copy_leaves_no_visible_or_partial_files(tmp_path, monkeypatch):
    spaces = FileSpaces(tmp_path / "data")
    source = tmp_path / "file.txt"; source.write_text("contents")
    def fail(source, destination):
        Path(destination).write_text("partial")
        raise OSError("disk full")
    monkeypatch.setattr("devicedrop.storage.spaces.shutil.copyfile", fail)
    with pytest.raises(OSError, match="disk full"):
        spaces.store([source])
    assert spaces.files() == [] and list(spaces.folder().iterdir()) == []


def test_device_folder_requires_uuid(tmp_path):
    spaces = FileSpaces(tmp_path)
    with pytest.raises(ValueError):
        spaces.folder("../../another-folder")


def test_general_root_and_named_private_folders_are_distinct(runtime, peer):
    from devicedrop.security.files import validate_filename
    assert runtime.spaces.folder() == Path(runtime.db.setting("sync_folder"))
    first = runtime.spaces.folder(peer["device_id"])
    assert first.name == peer["name"] and first.parent == runtime.spaces.root
    second_id = str(uuid4())
    runtime.db.trust({"device_id": second_id, "device_name": peer["name"], "platform": "android", "ip": "127.0.0.1", "port": 45833}, "x" * 32)
    second = runtime.spaces.folder(second_id)
    assert second != first and second.name.startswith(peer["name"])
    for name in ["../../outside", "CON", "Nombre:incorrecto*", "", "..", "A" * 99 + "." + "z"]:
        validate_filename(runtime.spaces.safe_name(name))


def test_legacy_space_migration_preserves_collisions_and_transfers(runtime, peer):
    general = runtime.root / "spaces" / "general"; general.mkdir(parents=True)
    private = runtime.root / "spaces" / "devices" / peer["device_id"]; private.mkdir(parents=True)
    (general / "note.txt").write_text("old general")
    (private / "private.txt").write_text("old private")
    (runtime.spaces.folder() / "note.txt").write_text("already here")
    old_path = str(general / "note.txt")
    runtime.db.execute("INSERT INTO transfers (transfer_id,original_path,status) VALUES ('old',?,'completed')", (old_path,))
    runtime.spaces.migrate_legacy()
    assert (runtime.spaces.folder() / "note.txt").read_text() == "already here"
    migrated = runtime.spaces.folder() / "note (1).txt"
    assert migrated.read_text() == "old general"
    assert (runtime.spaces.folder(peer["device_id"]) / "private.txt").read_text() == "old private"
    assert runtime.db.history()[0]["original_path"] == str(migrated)
    assert runtime.spaces.is_managed(migrated)
    runtime.spaces.migrate_legacy()
    assert len(runtime.spaces.files()) == 2


def test_private_files_send_only_to_owner_and_general_to_all(runtime, peer, tmp_path):
    runtime.online[peer["device_id"]] = True
    runtime.db.execute("UPDATE trusted_devices SET auto_sync=1")
    second_id = str(uuid4())
    runtime.db.trust({"device_id": second_id, "device_name": "Other", "platform": "windows", "ip": "127.0.0.1", "port": 45834}, "x" * 43)
    runtime.online[second_id] = True
    sent = []; runtime.send_files = lambda paths, ids, force=False: sent.append((paths, ids))
    private = runtime.spaces.folder(peer["device_id"]) / "private.txt"; private.write_text("private")
    runtime.sync_created(private)
    source = tmp_path / "copy.txt"; source.write_text("copied by UI")
    managed = runtime.spaces.store([source])[0]; runtime.sync_created(managed)
    assert sent == [([private], [peer["device_id"]])]
    manual = runtime.spaces.folder() / "manual.txt"; manual.write_text("new public file")
    runtime.sync_created(manual)
    assert sent[-1][0] == [manual]
    assert set(sent[-1][1]) == {peer["device_id"], second_id}
    with pytest.raises(ValueError, match="solo pueden enviarse"):
        type(runtime).send_files(runtime, [private], [second_id])


def test_default_general_folder_uses_home_filefastflow(tmp_path, monkeypatch):
    from devicedrop.runtime import Runtime
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("FILEFASTFLOW_DATA_ROOT", raising=False)
    monkeypatch.delenv("DEVICEDROP_DATA_ROOT", raising=False)
    app = Runtime()
    try:
        assert app.spaces.folder() == tmp_path / "home" / "filefastflow"
    finally:
        app.db.close()


def test_migrate_received_files_uses_sender_folder_without_overwriting(runtime, peer, tmp_path):
    old = tmp_path / "old-received"; old.mkdir()
    private = old / "note.txt"; private.write_text("private")
    general = old / "common.txt"; general.write_text("public")
    unrelated = old / "unrelated.txt"; unrelated.write_text("keep")
    existing = runtime.spaces.folder(peer["device_id"]) / "note.txt"; existing.write_text("existing")
    for scope, source in [("device", private), ("general", general)]:
        tid = str(uuid4())
        runtime.db.execute("INSERT INTO transfers (transfer_id,direction,status,saved_path,source_device,share_scope) VALUES (?,'incoming','completed',?,?,?)", (tid, str(source), peer["device_id"], scope))
        runtime.db.execute("INSERT INTO processed_files VALUES (?,?,?,?)", (peer["device_id"], scope, str(source), tid))
    runtime.spaces.migrate_received(old)
    assert existing.read_text() == "existing"
    migrated = existing.with_name("note (1).txt")
    assert migrated.read_text() == "private" and runtime.is_received_file(migrated)
    assert (runtime.spaces.folder() / "common.txt").read_text() == "public"
    assert not private.exists() and not general.exists() and unrelated.exists()
    runtime.spaces.migrate_received(old)
    assert len(runtime.spaces.files(peer["device_id"])) == 2

import json

import pytest

from picomms.model import ConfigError, ConfigLocked
from picomms.store import ConfigStore


def endpoint(**kw):
    d = dict(id="alex", name="Alex", listen=["tech"], talk=["tech"],
             listen_allowed=["tech"], talk_allowed=["tech"])
    d.update(kw)
    return d


def test_creates_defaults_and_persists(tmp_path):
    s = ConfigStore(tmp_path / "config.json")
    s.load()
    assert (tmp_path / "config.json").exists()
    s.upsert_endpoint(endpoint(address="aa:bb:cc:dd:ee:ff"))
    s2 = ConfigStore(tmp_path / "config.json")
    s2.load()
    assert s2.config.endpoint("alex").address == "AA:BB:CC:DD:EE:FF"


def test_show_mode_blocks_config_but_not_leaving_show_mode(tmp_path):
    s = ConfigStore(tmp_path / "config.json")
    s.load()
    s.set_show_mode(True)
    for fn in (
        lambda: s.upsert_endpoint(endpoint()),
        lambda: s.delete_endpoint("sound"),
        lambda: s.upsert_group({"id": "x", "name": "X"}),
        lambda: s.delete_group("tech"),
        lambda: s.set_dtmf({"prefix": "*"}),
        lambda: s.set_captions({"server": "x:1"}),
        lambda: s.set_attention_target(""),
        lambda: s.restore_json(s.export_json()),
    ):
        with pytest.raises(ConfigLocked):
            fn()
    s.set_show_mode(False)
    s.upsert_endpoint(endpoint())
    assert s.config.endpoint("alex")


def test_invalid_change_is_rejected_and_not_persisted(tmp_path):
    s = ConfigStore(tmp_path / "config.json")
    s.load()
    with pytest.raises(ConfigError):
        s.upsert_endpoint(endpoint(talk=["tech", "stage"]))  # exceeds talk_allowed
    assert s.config.endpoint("alex") is None
    on_disk = json.loads((tmp_path / "config.json").read_text())
    assert all(e["id"] != "alex" for e in on_disk["endpoints"])


def test_delete_group_cleans_references(tmp_path):
    s = ConfigStore(tmp_path / "config.json")
    s.load()
    s.upsert_endpoint(endpoint(listen=["tech", "stage"], listen_allowed=["tech", "stage"]))
    s.delete_group("stage")
    assert s.config.endpoint("alex").listen == ["tech"]
    assert "2" not in s.config.dtmf.commands  # select:stage removed


def test_corrupt_file_falls_back_to_backup_and_keeps_evidence(tmp_path):
    s = ConfigStore(tmp_path / "config.json")
    s.load()
    s.upsert_endpoint(endpoint())
    (tmp_path / "config.json").write_text("{ not json")
    s2 = ConfigStore(tmp_path / "config.json")
    s2.load()
    assert s2.config.endpoint("alex") is not None  # recovered from newest backup
    assert list(tmp_path.glob("config.broken-*"))


def test_export_restore_roundtrip(tmp_path):
    s = ConfigStore(tmp_path / "a" / "config.json")
    s.load()
    s.upsert_endpoint(endpoint())
    dump = s.export_json()
    t = ConfigStore(tmp_path / "b" / "config.json")
    t.load()
    t.restore_json(dump)
    assert t.config.to_dict() == s.config.to_dict()


def test_restore_rejects_garbage(tmp_path):
    s = ConfigStore(tmp_path / "config.json")
    s.load()
    with pytest.raises(Exception):
        s.restore_json('{"schema": 99}')
    assert s.config.endpoint("sound")


def test_listeners_notified(tmp_path):
    s = ConfigStore(tmp_path / "config.json")
    s.load()
    seen = []
    s.subscribe(lambda c: seen.append(c.show_mode))
    s.set_show_mode(True)
    assert seen == [True]

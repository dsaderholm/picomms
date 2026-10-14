"""Persistent configuration store with the show-mode configuration lock.

Single writer: only the engine process owns a ``ConfigStore``. The web process
asks the engine to make changes over the local control socket, so a crashed
web UI can never corrupt configuration and a crashed engine leaves the last
good file on disk.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .model import (
    Config, ConfigError, ConfigLocked, Endpoint, Group, default_config,
    normalize_mac, validate_action,
)

# Configuration keys that may still change while show mode is on. Everything
# else raises ConfigLocked. Mute, talk-mode, group *selection* and attention
# are runtime controls handled by the controller, not config, and are
# therefore never blocked by show mode.
SHOW_MODE_ALLOWED: set[str] = {"show_mode"}


class ConfigStore:
    def __init__(self, path: Path, backups: int = 20) -> None:
        self.path = Path(path)
        self.backups = backups
        self._cfg: Config = default_config()
        self._listeners: list[Callable[[Config], None]] = []

    # -- persistence --------------------------------------------------------
    def load(self) -> Config:
        if self.path.exists():
            try:
                self._cfg = Config.from_dict(json.loads(self.path.read_text()))
            except (json.JSONDecodeError, ConfigError, TypeError) as exc:
                # Never crash-loop on a bad file: keep it for forensics and
                # fall back to the newest good backup, then to defaults.
                broken = self.path.with_suffix(f".broken-{int(time.time())}")
                shutil.copy2(self.path, broken)
                self._cfg = self._load_latest_backup() or default_config()
                self._write_locked(self._cfg)
        else:
            self._cfg = default_config()
            self._write_locked(self._cfg)
        return self._cfg

    def _backup_dir(self) -> Path:
        return self.path.parent / "backups"

    def _load_latest_backup(self) -> Config | None:
        d = self._backup_dir()
        if not d.is_dir():
            return None
        for f in sorted(d.glob("config-*.json"), reverse=True):
            try:
                return Config.from_dict(json.loads(f.read_text()))
            except Exception:
                continue
        return None

    def _write_locked(self, cfg: Config) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(cfg.to_dict(), indent=2, sort_keys=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".config-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        bd = self._backup_dir()
        bd.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (bd / f"config-{stamp}.json").write_text(data)
        for old in sorted(bd.glob("config-*.json"))[:-self.backups]:
            old.unlink()

    # -- access -------------------------------------------------------------
    @property
    def config(self) -> Config:
        return self._cfg

    def subscribe(self, fn: Callable[[Config], None]) -> None:
        self._listeners.append(fn)

    def _commit(self, new: Config) -> Config:
        new.validate()
        self._cfg = new
        self._write_locked(new)
        for fn in self._listeners:
            fn(new)
        return new

    def _mutate(self, key: str, fn: Callable[[Config], None]) -> Config:
        if self._cfg.show_mode and key not in SHOW_MODE_ALLOWED:
            raise ConfigLocked(
                "Show mode is on: configuration changes are locked. "
                "Talk, mute and group-selection controls still work. "
                "Turn show mode off to change configuration."
            )
        new = Config.from_dict(self._cfg.to_dict())  # deep copy via validation
        fn(new)
        return self._commit(new)

    # -- mutations (each is one lock-checked, validated, persisted change) ---
    def set_show_mode(self, on: bool) -> Config:
        return self._mutate("show_mode", lambda c: setattr(c, "show_mode", bool(on)))

    def upsert_group(self, g: dict[str, Any]) -> Config:
        def fn(c: Config) -> None:
            grp = Group(**g)
            grp.validate()
            for i, old in enumerate(c.groups):
                if old.id == grp.id:
                    c.groups[i] = grp
                    return
            c.groups.append(grp)
        return self._mutate("groups", fn)

    def delete_group(self, gid: str) -> Config:
        def fn(c: Config) -> None:
            c.groups = [g for g in c.groups if g.id != gid]
            for e in c.endpoints:
                for attr in ("listen", "talk", "listen_allowed", "talk_allowed"):
                    setattr(e, attr, [x for x in getattr(e, attr) if x != gid])
            c.dtmf.commands = {
                d: a for d, a in c.dtmf.commands.items() if not a.endswith(f":{gid}")
            }
        return self._mutate("groups", fn)

    def upsert_endpoint(self, e: dict[str, Any]) -> Config:
        def fn(c: Config) -> None:
            data = dict(e)
            if data.get("address"):
                data["address"] = normalize_mac(data["address"])
            ep = Endpoint(**data)
            for i, old in enumerate(c.endpoints):
                if old.id == ep.id:
                    c.endpoints[i] = ep
                    return
            c.endpoints.append(ep)
        return self._mutate("endpoints", fn)

    def delete_endpoint(self, eid: str) -> Config:
        def fn(c: Config) -> None:
            c.endpoints = [e for e in c.endpoints if e.id != eid]
            if c.attention_target == eid:
                c.attention_target = ""
        return self._mutate("endpoints", fn)

    def set_dtmf(self, d: dict[str, Any]) -> Config:
        def fn(c: Config) -> None:
            for k, v in d.items():
                if not hasattr(c.dtmf, k):
                    raise ConfigError(f"unknown dtmf setting {k}")
                setattr(c.dtmf, k, v)
            for a in c.dtmf.commands.values():
                validate_action(a, {g.id for g in c.groups})
        return self._mutate("dtmf", fn)

    def set_captions(self, d: dict[str, Any]) -> Config:
        def fn(c: Config) -> None:
            for k, v in d.items():
                if not hasattr(c.captions, k):
                    raise ConfigError(f"unknown captions setting {k}")
                setattr(c.captions, k, v)
        return self._mutate("captions", fn)

    def set_attention_target(self, eid: str) -> Config:
        return self._mutate("attention", lambda c: setattr(c, "attention_target", eid))

    # -- backup / restore -----------------------------------------------------
    def export_json(self) -> str:
        return json.dumps(self._cfg.to_dict(), indent=2, sort_keys=True)

    def restore_json(self, text: str) -> Config:
        """Replace the whole configuration from an exported file (locked in show mode)."""
        if self._cfg.show_mode:
            raise ConfigLocked("Show mode is on: restore is locked.")
        new = Config.from_dict(json.loads(text))
        return self._commit(new)

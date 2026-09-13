from __future__ import annotations

from types import ModuleType

import yaml
from fastapi.testclient import TestClient
from ophyd import Component, Device, Signal

from ophyd_as_service.service import build_service, build_service_from_deployment_config


class FakeDevice(Device):
    def __init__(self, prefix: str, *, name: str, **kwargs):
        super().__init__(prefix=prefix, name=name, **kwargs)
        self._value = 0

    def describe(self):
        return {self.name: {"dtype": "integer", "shape": []}}

    def read(self):
        return {self.name: {"value": self._value, "timestamp": 0.0}}

    def put(self, value):
        self._value = value
        return {"status": "ok", "value": self._value}


class NestedChild(Device):
    leaf = Component(Signal, value=7)


class NestedDevice(Device):
    child = Component(NestedChild, "CHILD:")
    scalar = Component(Signal, value=3)


def _write_yaml(path, payload):
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(payload, stream)


def test_registration_happens_once_at_startup(tmp_path, monkeypatch):
    lib = ModuleType("fake_device_library")
    lib.DEVICES = {"fake": FakeDevice}
    monkeypatch.setitem(__import__("sys").modules, "fake_device_library", lib)

    device_config = tmp_path / "devices.yaml"
    deploy_config = tmp_path / "deployment.yaml"
    _write_yaml(
        device_config,
        {"devices": [{"name": "fake", "prefix": "SIM:", "alias": "det", "read_only": False}]},
    )
    _write_yaml(deploy_config, {"admin_token": "secret"})

    app = build_service("fake_device_library", str(device_config), str(deploy_config), single_process_mode=True)
    client = TestClient(app)

    assert client.get("/det/info").status_code == 200
    assert client.get("/det/capabilities").status_code == 200
    assert client.get("/det/read").status_code == 200

    # Registry changes after startup must not create new runtime endpoints.
    lib.DEVICES["other"] = FakeDevice
    assert client.get("/other/read").status_code == 404


def test_global_lock_blocks_put_but_allows_read(tmp_path, monkeypatch):
    lib = ModuleType("fake_lock_library")
    lib.DEVICES = {"fake": FakeDevice}
    monkeypatch.setitem(__import__("sys").modules, "fake_lock_library", lib)

    device_config = tmp_path / "devices.yaml"
    deploy_config = tmp_path / "deployment.yaml"
    _write_yaml(
        device_config,
        {"devices": [{"name": "fake", "prefix": "SIM:", "alias": "det", "read_only": False}]},
    )
    _write_yaml(deploy_config, {"admin_token": "secret"})

    app = build_service("fake_lock_library", str(device_config), str(deploy_config), single_process_mode=True)
    client = TestClient(app)

    assert client.put("/det/put", json={"value": 5}).status_code == 200

    assert client.post("/admin/lock/enable").status_code == 401
    assert (
        client.post(
            "/admin/lock/enable",
            headers={"X-Admin-Token": "secret"},
        ).status_code
        == 200
    )

    assert client.get("/det/read").status_code == 200
    assert client.put("/det/put", json={"value": 9}).status_code == 423

    assert (
        client.post(
            "/admin/lock/disable",
            headers={"X-Admin-Token": "secret"},
        ).status_code
        == 200
    )
    assert client.put("/det/put", json={"value": 9}).status_code == 200


def test_build_from_deployment_config_is_single_source(tmp_path, monkeypatch):
    lib = ModuleType("fake_deploy_source_library")
    lib.DEVICES = {"fake": FakeDevice}
    monkeypatch.setitem(__import__("sys").modules, "fake_deploy_source_library", lib)

    device_config = tmp_path / "devices.yaml"
    deploy_config = tmp_path / "deployment.yaml"
    _write_yaml(
        device_config,
        {"devices": [{"name": "fake", "prefix": "SIM:", "alias": "det", "read_only": False}]},
    )
    _write_yaml(
        deploy_config,
        {
            "library": "fake_deploy_source_library",
            "device_config": str(device_config),
            "admin_token": "secret",
            "single_process": True,
            "host": "127.0.0.1",
            "port": 8899,
        },
    )

    app, cfg = build_service_from_deployment_config(str(deploy_config))
    client = TestClient(app)

    assert cfg.library == "fake_deploy_source_library"
    assert cfg.device_config == str(device_config)
    assert cfg.single_process is True
    assert client.get("/det/describe").status_code == 200


def test_nested_component_read_and_describe_endpoints_exist(tmp_path, monkeypatch):
    lib = ModuleType("fake_nested_library")
    lib.DEVICES = {"nested": NestedDevice}
    monkeypatch.setitem(__import__("sys").modules, "fake_nested_library", lib)

    device_config = tmp_path / "devices.yaml"
    deploy_config = tmp_path / "deployment.yaml"
    _write_yaml(
        device_config,
        {"devices": [{"name": "nested", "prefix": "SIM:", "alias": "det", "read_only": False}]},
    )
    _write_yaml(deploy_config, {"admin_token": "secret"})

    app = build_service("fake_nested_library", str(device_config), str(deploy_config), single_process_mode=True)
    client = TestClient(app)

    assert client.get("/det/child/describe").status_code == 200
    assert client.get("/det/child/read").status_code == 200
    assert client.get("/det/child/leaf/describe").status_code == 200
    assert client.get("/det/child/leaf/read").status_code == 200
    assert client.get("/det/scalar/describe").status_code == 200
    assert client.get("/det/scalar/read").status_code == 200

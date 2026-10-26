from __future__ import annotations

from types import ModuleType

import pytest
import yaml
from fastapi.testclient import TestClient

from ophyd_as_service.service import build_service, build_service_from_deployment_config
from ophyd_as_service.tests.sample_devices import FakeDevice, NestedDevice


def _write_yaml(path, payload):
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(payload, stream)

@pytest.fixture
def deployment(tmp_path,monkeypatch):
    lib = ModuleType("fake_device_library")
    lib.DEVICES = {"Fake": FakeDevice}
    monkeypatch.setitem(__import__("sys").modules, "fake_device_library", lib)

    device_config = tmp_path / "devices.yaml"
    deploy_config = tmp_path / "deployment.yaml"
    _write_yaml(
        device_config,
        {"devices": {"Fake":{"prefix": "SIM:", "alias": "det", "read_only": False}}},
    )
    _write_yaml(deploy_config, {"admin_token": "secret"})
    return device_config, deploy_config

def test_registration_happens_once_at_startup(deployment):

    device_config, deploy_config = deployment

    app = build_service(
        library="ophyd_as_service.tests.sample_devices",
        device_config_path=str(device_config),
        single_process_mode=True)
    client = TestClient(app)

    assert client.get("/det/info").status_code == 200
    assert client.get("/det/capabilities").status_code == 404
    assert client.get("/det/read").status_code == 200



def test_global_lock_blocks_put_but_allows_read(deployment):

    device_config, deploy_config = deployment

    app = build_service("fake_device_library", str(device_config), str(deploy_config), single_process_mode=True)
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
        {"devices": {"fake":{"prefix": "SIM:", "alias": "det", "read_only": False}}},
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
        {"devices": { "nested":{ "prefix": "SIM:", "alias": "det", "read_only": False}}},
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


def test_device_ws_endpoints_are_scoped_to_their_alias(tmp_path, monkeypatch):
    lib = ModuleType("fake_scoped_library")
    lib.DEVICES = {"Fake": FakeDevice, "Other": FakeDevice}
    monkeypatch.setitem(__import__("sys").modules, "fake_scoped_library", lib)

    device_config = tmp_path / "devices.yaml"
    _write_yaml(
        device_config,
        {
            "devices": {
                "Fake": {"prefix": "SIM:", "alias": "det", "read_only": False},
                "Other": {"prefix": "SIM2:", "alias": "other", "read_only": False},
            }
        },
    )

    app = build_service("fake_scoped_library", str(device_config), single_process_mode=True)
    client = TestClient(app)

    with client.websocket_connect("/det/ws") as ws:
        ws.send_json({"type": "subscribe", "device": "other"})
        message = ws.receive_json()

    assert message["type"] == "error"
    assert "not allowed" in message["detail"].lower()


def test_finch_toggle_defaults_off_and_can_be_enabled(tmp_path, monkeypatch):
    lib = ModuleType("fake_finch_library")
    lib.DEVICES = {"Fake": FakeDevice}
    monkeypatch.setitem(__import__("sys").modules, "fake_finch_library", lib)

    device_config = tmp_path / "devices.yaml"
    deploy_config = tmp_path / "deployment.yaml"
    _write_yaml(
        device_config,
        {"devices": {"Fake": {"prefix": "SIM:", "alias": "det", "read_only": False}}},
    )
    _write_yaml(
        deploy_config,
        {
            "library": "fake_finch_library",
            "device_config": str(device_config),
            "finch_enabled": True,
        },
    )

    app, cfg = build_service_from_deployment_config(str(deploy_config))
    route_paths = {route.path for route in app.router.routes}

    assert cfg.finch_enabled is True
    assert "/ws" in route_paths or "/finch/ws" in route_paths

    _write_yaml(deploy_config, {"library": "fake_finch_library", "device_config": str(device_config)})
    app_default, cfg_default = build_service_from_deployment_config(str(deploy_config))

    assert cfg_default.finch_enabled is False


def test_generic_ws_batch_read_and_unique_path_subscriptions(tmp_path, monkeypatch):
    lib = ModuleType("fake_ws_batch_library")
    lib.DEVICES = {"nested": NestedDevice}
    monkeypatch.setitem(__import__("sys").modules, "fake_ws_batch_library", lib)

    device_config = tmp_path / "devices.yaml"
    _write_yaml(
        device_config,
        {"devices": { "nested":{ "prefix": "SIM:", "alias": "det", "read_only": False}}},
    )

    app = build_service("fake_ws_batch_library", str(device_config), single_process_mode=True)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        # Batch read multiple catalogue paths in one request
        ws.send_json({"action": "read", "paths": ["/det/child/leaf/read", "/det/scalar/read"]})
        read_resp = ws.receive_json()
        assert read_resp["type"] == "read"
        assert "/det/child/leaf/read" in read_resp["data"]
        assert "/det/scalar/read" in read_resp["data"]

        # Subscribe to duplicate paths; ensure deduplicated unique subscriptions
        ws.send_json({"action": "subscribe", "paths": ["/det/scalar", "/det/scalar", "/det/child/leaf"]})
        sub_resp = ws.receive_json()
        assert sub_resp["type"] == "subscribed"
        assert sub_resp["paths"] == ["/det/scalar", "/det/child/leaf"]


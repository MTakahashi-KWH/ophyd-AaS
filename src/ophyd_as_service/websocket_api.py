from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect

from .api import generate_catalogue
from .auth import AuthUnit
from .devices import LoadedDevice
from .handlers import Handler, HTTPVerb


@dataclass
class WebSocketSession:
    websocket: WebSocket
    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subscriptions: dict[str, Callable[[], None]] = field(default_factory=dict)
    active: bool = True


def _extract_value(value: Any) -> Any:
    is_primitive = isinstance(value, (dict, list, str, int, float, bool))
    return value if is_primitive else getattr(value, "value", value)


def _normalize_target_path(raw: str, verb: str = "read") -> str:
    clean = "/" + str(raw).strip("/")
    if clean.endswith((f"/{verb}", "/describe", "/info", "/spec")):
        return clean
    return f"{clean}/{verb}"


class CatalogueWebSocketManager:
    """Generic Bluesky/catalogue-oriented WebSocket interface.

    Supports:
    - Batch reads/describes across multiple catalogue paths in one request:
      {"action": "read", "paths": ["/det/read", "/det/child/leaf/read"]}
      -> {"type": "read", "data": {path: result}}
    - Unique path-keyed subscriptions firing `{path: value}` dictionaries:
      {"action": "subscribe", "paths": ["/det", "/det/child/leaf"]}
    """

    def __init__(
        self,
        catalogue: dict[str, Handler],
        devices: list[LoadedDevice] | None = None,
        allowed_aliases: set[str] | None = None,
        auth: AuthUnit | Callable[..., Any] | None = None,
        lock: Any = None,
    ):
        self.catalogue = catalogue
        self.devices = devices or []
        self._allowed_aliases = allowed_aliases
        self._auth = auth.require_admin if isinstance(auth, AuthUnit) else auth
        self.lock = lock
        self._sessions: dict[str, WebSocketSession] = {}

        # Map readable/subscribable paths to underlying ophyd objects
        self._targets: dict[str, Any] = {}
        for path, h in catalogue.items():
            target = getattr(h, "target", None)
            if target is not None and path.endswith("/read"):
                base = path[: -len("/read")] or "/"
                self._targets[path] = target
                self._targets[base] = target
                self._targets[base.lstrip("/")] = target
        for d in self.devices:
            for key in (getattr(d, "alias", None), getattr(d, "registry_key", None)):
                if key:
                    instance = getattr(d, "instance", d)
                    self._targets.setdefault(key, instance)
                    self._targets.setdefault(f"/{key}", instance)
                    self._targets.setdefault(f"/{key}/read", instance)

    def _check_alias(self, target: str) -> None:
        if self._allowed_aliases is None:
            return
        first_segment = target.strip("/").split("/", 1)[0]
        if first_segment not in self._allowed_aliases:
            allowed = ", ".join(sorted(self._allowed_aliases)) or "none"
            raise ValueError(
                f"Device '{first_segment}' is not allowed on this websocket endpoint. "
                f"Allowed devices: {allowed}"
            )

    async def connect(self, websocket: WebSocket) -> WebSocketSession:
        await websocket.accept()
        session = WebSocketSession(websocket=websocket)
        self._sessions[session.connection_id] = session
        return session

    async def disconnect(self, session: WebSocketSession) -> None:
        session.active = False
        for key in list(session.subscriptions):
            self.unsubscribe(session, key)
        self._sessions.pop(session.connection_id, None)

    async def batch_query(self, paths: list[str], verb: str = "read") -> dict[str, Any]:
        results: dict[str, Any] = {}
        for raw_path in paths:
            self._check_alias(raw_path)
            norm = _normalize_target_path(raw_path, verb=verb)
            handle = self.catalogue.get(norm) or self.catalogue.get("/" + str(raw_path).strip("/"))
            if handle is None or getattr(handle, "verb", HTTPVerb.GET) != HTTPVerb.GET:
                raise ValueError(f"Unknown catalogue path: {raw_path}")
            results[raw_path] = await handle()
        return results

    def subscribe(self, session: WebSocketSession, target_path: str) -> str:
        self._check_alias(target_path)
        if target_path in session.subscriptions:
            return target_path

        instance = self._targets.get(target_path) or self._targets.get(
            _normalize_target_path(target_path, "read")
        )
        if instance is None:
            raise ValueError(f"Unknown subscription path or device alias: {target_path}")

        loop = asyncio.get_running_loop()

        def on_value(value: Any, **kwargs: Any) -> None:
            if not session.active:
                return
            raw = _extract_value(value)
            payload = {
                "type": "event",
                "data": {target_path: raw},
                # Preserve top-level fields for compatibility with simple single-device consumers
                "subscription_id": target_path,
                "device": target_path,
                "value": raw,
            }
            loop.call_soon_threadsafe(loop.create_task, session.websocket.send_json(payload))

        try:
            token = instance.subscribe(callback=on_value, event_type=None, run=False)
        except (AttributeError, TypeError):
            token = None

        def _cleanup() -> None:
            if token is not None and hasattr(instance, "unsubscribe"):
                instance.unsubscribe(token)

        session.subscriptions[target_path] = _cleanup
        return target_path

    def unsubscribe(self, session: WebSocketSession, key: str) -> None:
        if cleanup := session.subscriptions.pop(key, None):
            cleanup()

    async def endpoint(self, websocket: WebSocket) -> None:
        session = await self.connect(websocket)
        await self.listen(websocket, session)

    def as_app(self, path: str = "/ws") -> FastAPI:
        app = FastAPI()
        self.register(app, path)
        return app

    def register(self, service: FastAPI, *paths: str) -> None:
        dependencies = [Depends(self._auth)] if self._auth else None
        for path in paths:
            service.add_api_websocket_route(path, self.endpoint, dependencies=dependencies)

    async def listen(self, websocket: WebSocket, session: WebSocketSession) -> None:
        try:
            while True:
                payload = await websocket.receive_json()
                action = payload.get("type") or payload.get("action") or "subscribe"
                raw_targets = (
                    payload.get("paths")
                    or ([t] if (t := payload.get("path") or payload.get("device")) else [])
                )
                targets = [str(t) for t in raw_targets if t]

                if action in {"read", "describe", "info", "spec"}:
                    if not targets:
                        await websocket.send_json(
                            {"type": "error", "detail": f"{action} payload requires a path or paths list"}
                        )
                        continue
                    try:
                        data = await self.batch_query(targets, verb=action)
                        await websocket.send_json({"type": action, "data": data})
                    except ValueError as exc:
                        await websocket.send_json({"type": "error", "detail": str(exc)})

                elif action == "subscribe":
                    if not targets:
                        await websocket.send_json(
                            {"type": "error", "detail": "subscribe payload requires a device, path, or paths list"}
                        )
                        continue
                    results = []
                    for target in dict.fromkeys(targets):
                        try:
                            sub_key = self.subscribe(session, target)
                            results.append({"subscription_id": sub_key, "device": target, "path": target})
                        except ValueError as exc:
                            await websocket.send_json({"type": "error", "detail": str(exc)})
                    if results:
                        msg = (
                            {**results[0], "paths": [r["path"] for r in results]}
                            if len(results) == 1
                            else {"subscriptions": results, "paths": [r["path"] for r in results]}
                        )
                        await websocket.send_json({"type": "subscribed", **msg})

                elif action == "unsubscribe":
                    unsub_targets = targets or (
                        [str(s)] if (s := payload.get("subscription_id")) else []
                    )
                    for key in unsub_targets:
                        self.unsubscribe(session, key)
                        await websocket.send_json(
                            {"type": "unsubscribed", "subscription_id": key, "path": key}
                        )

                elif action in {"close", "disconnect"}:
                    await self.disconnect(session)
                    break

                elif action == "ping":
                    await websocket.send_json({"type": "pong"})

                else:
                    await websocket.send_json(
                        {"type": "error", "detail": f"Unsupported websocket action: {action}"}
                    )
        except WebSocketDisconnect:
            await self.disconnect(session)


class FinchWebSocketManager(CatalogueWebSocketManager):
    """Dedicated Finch adapter translating Finch bind/bindings frames onto the catalogue manager."""

    async def listen(self, websocket: WebSocket, session: WebSocketSession) -> None:
        try:
            while True:
                payload = await websocket.receive_json()
                action = payload.get("type") or payload.get("action") or "bind"
                if action in {"bind", "subscribe"}:
                    raw_targets = (
                        payload.get("bindings")
                        or payload.get("paths")
                        or ([t] if (t := payload.get("binding") or payload.get("device")) else [])
                    )
                    targets = [str(t) for t in raw_targets if t]
                    if not targets:
                        await websocket.send_json(
                            {"type": "error", "detail": "bind payload requires a binding or bindings list"}
                        )
                        continue
                    results = []
                    for target in targets:
                        try:
                            sub_id = self.subscribe(session, target)
                            results.append({"subscription_id": sub_id, "device": target})
                        except ValueError as exc:
                            await websocket.send_json({"type": "error", "detail": str(exc)})
                    if results:
                        msg = results[0] if len(results) == 1 else {"subscriptions": results}
                        await websocket.send_json({"type": "subscribed", **msg})
                elif action == "unsubscribe":
                    if sub_id := payload.get("subscription_id"):
                        self.unsubscribe(session, str(sub_id))
                        await websocket.send_json({"type": "unsubscribed", "subscription_id": sub_id})
                elif action in {"close", "disconnect"}:
                    await self.disconnect(session)
                    break
                elif action == "ping":
                    await websocket.send_json({"type": "pong"})
                else:
                    await websocket.send_json(
                        {"type": "error", "detail": f"Unsupported finch action: {action}"}
                    )
        except WebSocketDisconnect:
            await self.disconnect(session)


# Alias for backward compatibility
SubscriptionManager = CatalogueWebSocketManager


def _build_combined_catalogue(
    devices: list[LoadedDevice],
    catalogue: dict[str, Handler] | None = None,
    lock: Any = None,
) -> dict[str, Handler]:
    if catalogue is not None:
        return catalogue
    combined: dict[str, Handler] = {}
    for device in devices:
        combined.update(generate_catalogue(device, lock=lock))
    return combined


def register_standard_ws_support(
    service: FastAPI,
    devices: list[LoadedDevice],
    catalogue: dict[str, Handler] | None = None,
    auth: AuthUnit | Callable[..., Any] | None = None,
    lock: Any = None,
) -> CatalogueWebSocketManager:
    combined = _build_combined_catalogue(devices, catalogue=catalogue, lock=lock)
    manager = CatalogueWebSocketManager(combined, devices=devices, auth=auth, lock=lock)
    manager.register(service, "/ws")

    for device in devices:
        dev_cat = {k: v for k, v in combined.items() if k.startswith(f"/{device.alias}/")}
        scoped = CatalogueWebSocketManager(
            dev_cat,
            devices=[device],
            allowed_aliases={device.alias},
            auth=auth,
            lock=lock,
        )
        scoped.register(service, f"/{device.alias}/subscribe", f"/{device.alias}/ws")

    return manager


def register_finch_support(
    service: FastAPI,
    devices: list[LoadedDevice],
    catalogue: dict[str, Handler] | None = None,
    auth: AuthUnit | Callable[..., Any] | None = None,
    lock: Any = None,
    mount_subapp: bool = True,
) -> FinchWebSocketManager:
    combined = _build_combined_catalogue(devices, catalogue=catalogue, lock=lock)
    manager = FinchWebSocketManager(combined, devices=devices, auth=auth, lock=lock)
    if mount_subapp:
        service.mount("/finch", manager.as_app("/ws"))
    else:
        manager.register(service, "/finch/ws")
    return manager



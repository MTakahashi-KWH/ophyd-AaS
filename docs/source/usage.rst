=============================
Starting and Using the Server
=============================

Start the service:

.. code-block:: bash

	python -m ophyd_as_service.service --deployment-config /path/to/deployment.yaml

Optional overrides:

- ``--single-process``: force single-process mode.
- ``--per-device-process``: force per-device mount mode.
- ``--host`` and ``--port``: override deployment-config network settings.

Core Device Endpoints
=====================

For each configured alias ``{alias}``, the service provides:

- ``GET /{alias}/describe``
- ``GET /{alias}/read``
- ``PUT /{alias}/put`` with JSON body ``{"value": ...}``
- ``GET /{alias}/info``
- ``GET /{alias}/capabilities``

Lock and Admin Endpoints
========================

- ``GET /admin/lock/status``
- ``POST /admin/lock/enable`` (requires header ``X-Admin-Token``)
- ``POST /admin/lock/disable`` (requires header ``X-Admin-Token``)
- ``GET /admin/devices`` (requires header ``X-Admin-Token``)

When lock is enabled, reads are still allowed while mutating ``PUT`` endpoints
return HTTP 423.

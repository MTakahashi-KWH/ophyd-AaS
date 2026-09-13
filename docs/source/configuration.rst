====================
Server Configuration
====================

The deployment configuration file is the single source of truth for what gets
registered when the service starts.

Startup-only registration
=========================

Device registration happens exactly once at startup. The service does not
support runtime add/remove or hot-reload of devices in MVP mode.

Deployment Config
=================

Required keys:

- ``library``: Python module path for the deployment library exposing
	``DEVICES`` or ``ophyd.DEVICES``.
- ``device_config``: Path to the device-selection YAML file.
- ``admin_token``: Static admin token used for lock-management endpoints.

Optional keys:

- ``single_process``: bool, defaults to ``true``.
- ``host``: bind address, defaults to ``0.0.0.0``.
- ``port``: bind port, defaults to ``8000``.

Example deployment config:

.. code-block:: yaml

	 library: ophyd_as_service.test_devices
	 device_config: /path/to/devices.yaml
	 admin_token: change-me
	 single_process: true
	 host: 0.0.0.0
	 port: 8000

Example device config:

.. code-block:: yaml

	 devices:
		 - name: "tpx:pipe"
			 prefix: "tpx:pipe:"
			 alias: "tpx_pipe"
			 read_only: false

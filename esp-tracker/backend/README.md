# esptracker backend

Python ground-station application for the ESP-NOW ELRS antenna tracker: it reads the JSON lines
sent by the tracker firmware over USB/serial, keeps the live state, serves a web UI (map, telemetry,
tracker controls) and forwards commands back to the tracker.

Full documentation: [`../docs/usage.md`](../docs/usage.md) (how to run it) and
[`../docs/architecture.md`](../docs/architecture.md) (how it works).

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install .            # or: pip install -e '.[test]' for development
esptracker --simulate    # no hardware needed: fake flight around Paris
esptracker --port auto   # real tracker on USB
# then open http://127.0.0.1:8080
```

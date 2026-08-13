# Phase 2 - Alert integration and lifecycle

## Tasks

- [x] Inject an optional notifier into `IngestionService`; enqueue threshold
  alerts only when `state=open` and `occurrence_count=1`.
- [x] Enqueue every newly inserted fall event after existing `(device_id,
  event_id)` dedup; do not enqueue duplicate retransmissions.
- [x] Ensure notifier enqueue exceptions/full queues cannot change a valid
  `IngestResult` or ingestion metrics into a processing failure.
- [x] Construct, start, and stop the notifier through `create_app()` lifespan in
  `edge/app.py`; disabled mode creates no worker.
- [x] Add ingestion tests for new threshold, touch, reopen, new fall, duplicate
  fall, queue full, and notifier exception behavior.
- [x] Add API/lifespan regression coverage without changing response schemas.

## Verification

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_rules.py tests/test_ingestion.py tests/test_api.py -q
```

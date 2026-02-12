# Snapshot API Contract (WinUI Phase 1)

Base URL is injected to frontend through environment variables:
- `BOMANA_SNAPSHOT_API_URL` (full `/snapshot` URL)
- `BOMANA_SNAPSHOT_HEALTH_URL` (full `/health` URL)
- `BOMANA_UI_BRIDGE_HOST`
- `BOMANA_UI_BRIDGE_PORT`

## Endpoints

### `GET /health`
Returns bridge status.

Example fields:
- `ok`
- `service`
- `version`
- `schema_version`
- `uptime_sec`
- `last_snapshot_at`
- `api_down`
- `last_error`

### `GET /snapshot`
Returns latest flattened game snapshot for UI rendering.

Key fields:
- `phase`, `sortie_id`, `life_index`, `cycle`
- `remaining_sec`, `remaining_text`, `progress`
- `status_text`
- `main_badge`, `flight_badge`
- `api_down`, `api_down_pending`
- `zones`, `target_zone`
- `friendly_airfield`, `enemy_airfields`
- `fuel_kg`, `fuel_percent`, `fuel_time_remaining_str`
- `attitude_pitch_deg`, `attitude_roll_deg`, `attitude_reliable`
- `diag_text`

## Polling Guideline
- Recommended frontend polling interval: `50-100ms`
- Backend tick cadence follows `NetworkConfig` (`POLL_INTERVAL` / `BACKOFF_MAX`)

## Compatibility
- `schema_version` currently `1`
- Additive fields are allowed
- Breaking field changes must bump `schema_version`

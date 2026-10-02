# Configuration and API

## File locations

Source folders must be inside `/config/www`, a configured Home Assistant media directory, or a directory explicitly listed in `homeassistant.allowlist_external_dirs`. The panel shows the permitted roots. Paths are resolved and escaping symlinks are rejected. Source folders are scanned non-recursively.

Video outputs must stay inside a configured media directory or `/config/ha_tgen`. Outputs under `www` are intentionally unsupported so generated videos remain private. An output directory cannot be changed while indexed videos or pending jobs exist. Remove generated videos and cancel jobs first, or leave the existing archive location unchanged.

For an external source on HA OS or Container, make it accessible inside the HA container and add its container path to `homeassistant.allowlist_external_dirs` when it is outside a media folder. This allowlist is HA's existing configuration; the integration does not mount host directories.

Config entry data holds the initial output root. Detailed settings, stable UUID camera IDs, job history, archive index and schedule markers are held in the versioned `.storage/ha_tgen.data` Store. HA backups include this configuration; verify that your backup also includes your chosen media directory if you want to back up video files. Removing the integration does not delete source photos or archived MP4 files.

## Camera fields

| Field | Default | Accepted values |
| --- | --- | --- |
| `name` | required | 1–100 characters |
| `source_dir` | required | Existing absolute directory inside a permitted source root |
| `prefix` | empty | Literal filename prefix, case-insensitive |
| `timestamp_format` | `%Y%m%d_%H%M%S` | Python strptime format containing `%Y`, `%m`, `%d` |
| `fps` | 12 | Integer 1–60; weekly, monthly and custom |
| `yearly_fps` | 24 | Integer 1–60 |
| `crf` | 23 | Integer 0–51 |
| `resolution` | `source` | First valid photo's even dimensions, `720p`, `1080p`, `2160p` |
| `timeout` | 3600 | Integer 10–86400 seconds |

Timestamp dates represent the HA local calendar. All supported images are resized to one output size, preserving their aspect ratio with black padding. EXIF orientation is applied. One accepted photo becomes exactly one video frame. Photos captured at irregular intervals are still shown at the selected constant FPS.

The queue allows 100 pending/running jobs. History keeps the last 500 completed jobs; this does not delete their videos. Warnings include a total skipped count and up to 20 filename/error samples. Encoder stderr is bounded; no unbounded per-frame logs are stored.

## Home Assistant actions

Find a camera's stable ID in **Cameras → Camera ID**.

```yaml
action: ha_tgen.generate
data:
  camera_ids:
    - "2d3f9681a6e945f98da5e70aace1d232"
  mode: custom
  start_date: "2026-09-01"
  end_date: "2026-09-30"
response_variable: timelapse
```

The optional response is `{"job_ids": ["..."]}`. Other modes are `weekly`, `monthly` and `yearly`. Queue acceptance does not mean the video has finished; follow its status in the panel.

```yaml
action: ha_tgen.cancel
data:
  job_id: "the-job-id-returned-by-generate"
```

Interactive calls require an administrator. HA automations with no user context are allowed.

## WebSocket interface

All commands use the existing authenticated Home Assistant WebSocket connection.

| Command | Purpose |
| --- | --- |
| `ha_tgen/state` | Current settings, cameras, jobs and videos; viewers receive only camera names/IDs and gallery data |
| `ha_tgen/subscribe` | Push state changes; unsubscribe through HA's standard subscription command |
| `ha_tgen/manage` | Administrator-only operation; takes `action` and `data` |
| `ha_tgen/video_url` | Takes an indexed `video_id`; returns a ten-minute signed playback/download URL |

Management actions are `save_camera`, `delete_camera`, `preview`, `save_settings`, `generate`, `cancel`, `retry`, `delete_video`. Camera save accepts the fields above plus optional existing `id`; deletion/cancellation/retry uses `{"id": "..."}`. Preview accepts a camera definition and returns count, skipped count, samples and warnings. Settings save takes `output_root` and `retention_days` (`0` disables retention). Generate uses the same fields as the HA action.

`GET` and `HEAD /api/ha_tgen/video/{id}` require HA authentication or a valid signed path and support HTTP Range requests. Signed URLs are temporary credentials and should not be posted publicly. No endpoint accepts a raw filesystem path for media playback or deletion.

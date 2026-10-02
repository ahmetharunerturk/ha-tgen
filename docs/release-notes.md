First public release of HA Timelapse Generator.

- HACS integration with an English/Turkish sidebar panel.
- Multiple timestamped photo sources, configurable video settings and filename preview.
- Weekly, monthly, year-to-date and inclusive custom timelapses.
- Automatic schedules, a serial background queue, progress, cancellation and retry.
- Private dated video library with playback, downloads, filters and optional retention.
- Source photographs remain untouched.

Requires Home Assistant 2026.9 or newer and FFmpeg with libx264. Add this repository to HACS as an Integration, download it, restart HA and add HA Timelapse Generator from Devices & services.

This is v0.1.0. Automated tests cover the encoding engine, the HA adapter and the browser panel; physical HA OS hardware validation is still recommended before moving a long-running photo archive's production schedules.

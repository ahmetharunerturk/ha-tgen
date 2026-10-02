"""Home Assistant lifecycle adapter for the timelapse engine."""

from __future__ import annotations

from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from .const import DOMAIN, STORAGE_KEY, STORAGE_VERSION, VERSION
from .encoder import EncodingError, check_ffmpeg
from .manager import TimelapseManager

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


def directory_roots(hass: HomeAssistant) -> tuple[list[str], list[str]]:
    """Keep output private; permit sources from www, media and explicit allowlists."""
    media = list(hass.config.media_dirs.values())
    sources = [hass.config.path("www"), *media, *hass.config.allowlist_external_dirs]
    outputs = [*media, hass.config.path("ha_tgen")]
    return list(dict.fromkeys(sources)), list(dict.fromkeys(outputs))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load storage, register a panel, and start one owned background worker."""
    from homeassistant.components.ffmpeg import get_ffmpeg_manager
    from homeassistant.components.http import StaticPathConfig
    from homeassistant.components.panel_custom import async_register_panel
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    from homeassistant.exceptions import ConfigEntryNotReady
    from homeassistant.helpers.event import async_track_time_interval
    from homeassistant.helpers.importlib import async_import_module
    from homeassistant.helpers.storage import Store

    api = await async_import_module(hass, f"{__name__}.api")

    async def executor(func, *args, **kwargs):
        return await hass.async_add_executor_job(partial(func, *args, **kwargs))

    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    sources, outputs = directory_roots(hass)
    binary = get_ffmpeg_manager(hass).binary
    try:
        await check_ffmpeg(binary)
        manager = TimelapseManager(
            executor=executor,
            save=store.async_save,
            source_roots=sources,
            output_roots=outputs,
            binary=binary,
            timezone_name=hass.config.time_zone,
            output_root=entry.data["output_root"],
            data=await store.async_load(),
        )
        await manager.start()
    except (OSError, ValueError, RuntimeError, EncodingError) as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = manager
    # HTTP routes and websocket command registration survive integration reloads.
    if not hass.data.get(f"{DOMAIN}_api_registered"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/ha_tgen_static", str(Path(__file__).parent / "frontend"), True)]
        )
        api.async_register_api(hass)
        hass.data[f"{DOMAIN}_api_registered"] = True
    hass.data[DOMAIN] = manager
    api.async_register_services(hass)
    await async_register_panel(
        hass,
        frontend_url_path="ha-tgen",
        webcomponent_name="ha-tgen-panel",
        sidebar_title="Timelapse",
        sidebar_icon="mdi:video-vintage",
        module_url=f"/ha_tgen_static/panel.js?v={VERSION}",
        require_admin=False,
        config_panel_domain=DOMAIN,
    )

    async def tick(now):
        manager.timezone_name = hass.config.time_zone
        await manager.tick(now)

    async def shutdown(_event):
        await manager.close()

    entry.async_on_unload(async_track_time_interval(hass, tick, timedelta(seconds=30)))
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop child processes and remove the panel and registered actions."""
    from homeassistant.components.frontend import async_remove_panel

    await entry.runtime_data.close()
    hass.data.pop(DOMAIN, None)
    async_remove_panel(hass, "ha-tgen")
    for service in ("generate", "cancel"):
        hass.services.async_remove(DOMAIN, service)
    return True

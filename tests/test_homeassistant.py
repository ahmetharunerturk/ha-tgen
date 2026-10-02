"""Exercise the real HA service registry, websocket decorators, Store and HTTP auth.

Runs on Linux CI with Home Assistant installed; local pure-engine tests work on Windows.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

pytest.importorskip("homeassistant", reason="Home Assistant adapter tests run on Linux CI")

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from homeassistant.auth import auth_manager_from_config
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_READ_ONLY
from homeassistant.components.http import KEY_HASS
from homeassistant.components.http.auth import async_setup_auth, async_sign_path
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized

from custom_components.ha_tgen import async_setup_entry, async_unload_entry
from custom_components.ha_tgen.api import TimelapseVideoView
from custom_components.ha_tgen.config_flow import TimelapseConfigFlow
from custom_components.ha_tgen.const import DOMAIN
from custom_components.ha_tgen.models import Video, new_id

pytestmark = pytest.mark.ha


@pytest.fixture
async def ha(tmp_path, ffmpeg):
    hass = HomeAssistant(str(tmp_path))
    hass.config.time_zone = "Europe/Berlin"
    media = tmp_path / "media"
    media.mkdir()
    (tmp_path / "www").mkdir()
    hass.config.media_dirs = {"local": str(media)}
    hass.auth = await auth_manager_from_config(hass, [], [])
    admin = await hass.auth.async_create_user("Admin", group_ids=[GROUP_ID_ADMIN])
    viewer = await hass.auth.async_create_user("Viewer", group_ids=[GROUP_ID_READ_ONLY])
    admin_token = await hass.auth.async_create_refresh_token(admin, client_id="http://localhost")
    viewer_token = await hass.auth.async_create_refresh_token(viewer, client_id="http://localhost")
    hass.http = SimpleNamespace(async_register_static_paths=AsyncMock(), register_view=Mock())
    hass.data["ffmpeg"] = SimpleNamespace(binary=ffmpeg)
    callbacks = []
    entry = SimpleNamespace(data={"output_root": str(media / "ha_tgen")}, async_on_unload=callbacks.append)
    with (
        patch(
            "homeassistant.components.panel_custom.async_register_panel", new_callable=AsyncMock
        ) as register,
        patch("homeassistant.components.frontend.async_remove_panel"),
    ):
        assert await async_setup_entry(hass, entry)
        yield SimpleNamespace(
            hass=hass,
            entry=entry,
            register=register,
            admin=admin,
            viewer=viewer,
            admin_token=admin_token,
            viewer_token=viewer_token,
            callbacks=callbacks,
        )
        if DOMAIN in hass.data:
            await async_unload_entry(hass, entry)
        for callback in callbacks:
            callback()
        await hass.async_stop(force=True)


async def test_setup_unload_reload_restores_store_without_duplicate_routes(ha):
    manager = ha.entry.runtime_data
    await manager.put_camera({"name": "Garden", "source_dir": ha.hass.config.path("www")})
    assert ha.register.await_args.kwargs["frontend_url_path"] == "ha-tgen"
    assert ha.hass.services.has_service(DOMAIN, "generate")
    await async_unload_entry(ha.hass, ha.entry)
    assert manager.worker is None
    assert not ha.hass.services.has_service(DOMAIN, "generate")
    for callback in ha.callbacks:
        callback()
    ha.callbacks.clear()
    assert await async_setup_entry(ha.hass, ha.entry)
    assert len(ha.entry.runtime_data.cameras) == 1
    assert ha.hass.http.register_view.call_count == 1
    assert ha.hass.http.async_register_static_paths.await_count == 1


async def test_config_flow_validates_private_output_location(ha):
    flow = TimelapseConfigFlow()
    flow.hass = ha.hass
    flow.context = {}
    flow._async_current_entries = lambda: []
    invalid = await flow.async_step_user({"output_root": ha.hass.config.path("www", "videos")})
    assert invalid["errors"] == {"output_root": "invalid_directory"}
    valid = await flow.async_step_user({"output_root": ha.entry.runtime_data.settings.output_root})
    assert valid["type"] == "create_entry"


async def test_services_reject_viewers_and_return_job_ids_to_admin(ha):
    camera = await ha.entry.runtime_data.put_camera(
        {"name": "Garden", "source_dir": ha.hass.config.path("www")}
    )
    data = {"camera_ids": [camera["id"]], "mode": "weekly"}
    with pytest.raises(Unauthorized):
        await ha.hass.services.async_call(
            DOMAIN,
            "generate",
            data,
            blocking=True,
            return_response=True,
            context=Context(user_id=ha.viewer.id),
        )
    assert not ha.entry.runtime_data.jobs
    result = await ha.hass.services.async_call(
        DOMAIN, "generate", data, blocking=True, return_response=True, context=Context(user_id=ha.admin.id)
    )
    assert len(result["job_ids"]) == 1
    await ha.entry.runtime_data.queue.join()


async def test_websocket_enforces_admin_and_filters_read_only_state(ha):
    outbox = asyncio.Queue()

    def receive(value):
        outbox.put_nowait(json.loads(value) if isinstance(value, (str, bytes)) else value)

    connection = ActiveConnection(
        logging.getLogger("test.websocket"), ha.hass, receive, ha.viewer, ha.viewer_token, "127.0.0.1"
    )
    connection.async_handle({"id": 1, "type": "ha_tgen/manage", "action": "save_settings", "data": {}})
    reply = await asyncio.wait_for(outbox.get(), 5)
    assert reply["error"]["code"] == "unauthorized"
    connection.async_handle({"id": 2, "type": "ha_tgen/state"})
    reply = await asyncio.wait_for(outbox.get(), 5)
    assert reply["result"]["settings"] == {}
    assert reply["result"]["source_roots"] == []
    connection.async_handle({"id": 3, "type": "ha_tgen/subscribe"})
    assert (await asyncio.wait_for(outbox.get(), 5))["success"]
    assert (await asyncio.wait_for(outbox.get(), 5))["type"] == "event"
    manager = ha.entry.runtime_data
    video_id = new_id()
    manager.videos[video_id] = Video(
        video_id,
        new_id(),
        "Camera",
        "weekly",
        "2026-09-21",
        "2026-09-27",
        datetime.now(timezone.utc).isoformat(),
        "test.mp4",
        3,
        12,
        10,
    )
    connection.async_handle({"id": 4, "type": "ha_tgen/video_url", "video_id": video_id})
    reply = await asyncio.wait_for(outbox.get(), 5)
    assert reply["id"] == 4 and reply["success"]
    assert f"/api/ha_tgen/video/{video_id}?" in reply["result"]["url"]
    connection.async_handle_close()
    assert not ha.entry.runtime_data.listeners


async def test_http_auth_signed_paths_range_head_and_path_bounds(ha):
    manager = ha.entry.runtime_data
    video_id = new_id()
    path = manager.settings.output_root + "/test.mp4"
    payload = b"0123456789abcdefghijklmnopqrstuvwxyz"
    await asyncio.to_thread(lambda: __import__("pathlib").Path(path).write_bytes(payload))
    manager.videos[video_id] = Video(
        video_id,
        new_id(),
        "Camera",
        "custom",
        "2026-10-02",
        "2026-10-02",
        datetime.now(timezone.utc).isoformat(),
        "test.mp4",
        3,
        12,
        len(payload),
    )
    app = web.Application()
    app[KEY_HASS] = ha.hass
    await async_setup_auth(ha.hass, app)
    TimelapseVideoView().register(ha.hass, app, app.router)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        url = f"/api/ha_tgen/video/{video_id}"
        assert (await client.get(url)).status == 401
        headers = {
            "Authorization": f"Bearer {ha.hass.auth.async_create_access_token(ha.viewer_token)}",
            "Range": "bytes=5-9",
        }
        response = await client.get(url, headers=headers)
        assert response.status == 206
        assert await response.read() == b"56789"
        assert response.headers["Content-Range"] == f"bytes 5-9/{len(payload)}"
        signed = async_sign_path(ha.hass, url, timedelta(minutes=10), refresh_token_id=ha.viewer_token.id)
        assert (await client.get(signed)).status == 200
        response = await client.head(signed)
        assert response.status == 200 and await response.read() == b""
        expired = async_sign_path(ha.hass, url, timedelta(seconds=-1), refresh_token_id=ha.viewer_token.id)
        assert (await client.get(expired)).status == 401
        assert (await client.get(signed.replace(video_id, new_id()))).status == 401
        response = await client.get("/api/ha_tgen/video/not-an-id", headers=headers)
        assert response.status == 404
        manager.videos[video_id].filename = "../outside.mp4"
        assert (await client.get(url, headers=headers)).status == 404
    finally:
        await client.close()

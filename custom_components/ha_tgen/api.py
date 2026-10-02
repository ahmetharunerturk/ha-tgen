"""Authenticated websocket, action and HTTP Range interfaces."""

from datetime import timedelta

import voluptuous as vol
from aiohttp import web
from homeassistant.components import websocket_api
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized

from .const import DOMAIN, MODES


def manager_for(hass):
    if DOMAIN not in hass.data:
        raise HomeAssistantError("Timelapse integration is not loaded")
    return hass.data[DOMAIN]


@websocket_api.websocket_command({"type": "ha_tgen/state"})
@websocket_api.async_response
async def ws_state(hass, connection, msg):
    connection.send_result(msg["id"], manager_for(hass).state(connection.user.is_admin))


@websocket_api.websocket_command({"type": "ha_tgen/subscribe"})
@websocket_api.async_response
async def ws_subscribe(hass, connection, msg):
    manager = manager_for(hass)

    @callback
    def publish():
        connection.send_event(msg["id"], manager.state(connection.user.is_admin))

    manager.listeners.add(publish)
    connection.subscriptions[msg["id"]] = lambda: manager.listeners.discard(publish)
    connection.send_result(msg["id"])
    publish()


@websocket_api.websocket_command(
    {
        "type": "ha_tgen/manage",
        vol.Required("action"): vol.In(
            (
                "save_camera",
                "delete_camera",
                "preview",
                "save_settings",
                "generate",
                "cancel",
                "retry",
                "delete_video",
            )
        ),
        vol.Optional("data", default=dict): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_manage(hass, connection, msg):
    manager, data, action = manager_for(hass), msg["data"], msg["action"]
    try:
        result = None
        if action == "save_camera":
            result = await manager.put_camera(data)
        elif action == "delete_camera":
            await manager.delete_camera(data.get("id", ""))
        elif action == "preview":
            result = await manager.preview(data)
        elif action == "save_settings":
            await manager.put_settings(data)
        elif action == "generate":
            result = {
                "job_ids": await manager.generate(
                    data.get("camera_ids", []),
                    data.get("mode", ""),
                    data.get("start_date"),
                    data.get("end_date"),
                )
            }
        elif action == "cancel":
            await manager.cancel(data.get("id", ""))
        elif action == "retry":
            result = {"job_ids": await manager.retry(data.get("id", ""))}
        elif action == "delete_video":
            await manager.delete_video(data.get("id", ""))
        connection.send_result(msg["id"], result)
    except (ValueError, OSError) as err:
        connection.send_error(msg["id"], "invalid_request", str(err))


@websocket_api.websocket_command({"type": "ha_tgen/video_url", vol.Required("video_id"): str})
@websocket_api.async_response
async def ws_video_url(hass, connection, msg):
    try:
        # Only indexed videos may receive a signed URL; never accept an arbitrary path.
        await manager_for(hass).video_path(msg["video_id"])
        connection.send_result(
            msg["id"],
            {
                "url": async_sign_path(
                    hass,
                    f"/api/ha_tgen/video/{msg['video_id']}",
                    timedelta(minutes=10),
                )
            },
        )
    except ValueError as err:
        connection.send_error(msg["id"], "not_found", str(err))


class TimelapseVideoView(HomeAssistantView):
    """Aiohttp FileResponse supplies Range/HEAD and file I/O in its executor."""

    url = "/api/ha_tgen/video/{video_id}"
    name = "api:ha_tgen:video"
    requires_auth = True

    async def get(self, request, video_id):
        hass = request.app[KEY_HASS]
        try:
            path = await manager_for(hass).video_path(video_id)
            exists = await hass.async_add_executor_job(path.is_file)
            if not exists:
                raise ValueError("Video file no longer exists")
        except (ValueError, OSError) as err:
            raise web.HTTPNotFound(text=str(err)) from err
        return web.FileResponse(
            path,
            headers={
                "Content-Type": "video/mp4",
                "Cache-Control": "private, no-store",
                "Content-Disposition": f'inline; filename="{path.name}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def head(self, request, video_id):
        return await self.get(request, video_id)


@callback
def async_register_api(hass):
    for command in (ws_state, ws_subscribe, ws_manage, ws_video_url):
        websocket_api.async_register_command(hass, command)
    hass.http.register_view(TimelapseVideoView())


async def require_service_admin(hass, call):
    # Automated calls have no user context. Interactive calls must be administrators.
    if call.context.user_id:
        user = await hass.auth.async_get_user(call.context.user_id)
        if user is None or not user.is_admin:
            raise Unauthorized()


@callback
def async_register_services(hass):
    async def generate(call):
        await require_service_admin(hass, call)
        try:
            job_ids = await manager_for(hass).generate(
                call.data["camera_ids"],
                call.data["mode"],
                call.data.get("start_date"),
                call.data.get("end_date"),
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        return {"job_ids": job_ids}

    async def cancel(call):
        await require_service_admin(hass, call)
        try:
            await manager_for(hass).cancel(call.data["job_id"])
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    hass.services.async_register(
        DOMAIN,
        "generate",
        generate,
        schema=vol.Schema(
            {
                vol.Required("camera_ids"): [str],
                vol.Required("mode"): vol.In(MODES),
                vol.Optional("start_date"): str,
                vol.Optional("end_date"): str,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, "cancel", cancel, schema=vol.Schema({vol.Required("job_id"): str}))

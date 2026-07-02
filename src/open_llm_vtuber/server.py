"""
Open-LLM-VTuber Server
========================
This module contains the WebSocket server for Open-LLM-VTuber, which handles
the WebSocket connections, serves static files, and manages the web tool.
It uses FastAPI for the server and Starlette for static file serving.
"""

import os
import shutil

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response, FileResponse
from starlette.staticfiles import StaticFiles as StarletteStaticFiles

from .routes import init_client_ws_route, init_webtool_routes, init_proxy_route
from .service_context import ServiceContext
from .config_manager.utils import Config


# Create a custom StaticFiles class that adds CORS headers
class CORSStaticFiles(StarletteStaticFiles):
    """
    Static files handler that adds CORS headers to all responses.
    Needed because Starlette StaticFiles might bypass standard middleware.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)

        # Add CORS headers to all responses
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"

        if path.endswith(".js"):
            response.headers["Content-Type"] = "application/javascript"

        return response


class AvatarStaticFiles(CORSStaticFiles):
    """
    Avatar files handler with security restrictions and CORS headers
    """

    async def get_response(self, path: str, scope):
        allowed_extensions = (".jpg", ".jpeg", ".png", ".gif", ".svg")
        if not any(path.lower().endswith(ext) for ext in allowed_extensions):
            return Response("Forbidden file type", status_code=403)
        response = await super().get_response(path, scope)
        return response


class FrontendStaticFiles(CORSStaticFiles):
    """
    Serves the built frontend and injects the GIF-overlay script into index.html
    on the fly, so the frontend submodule itself stays untouched.
    """

    _INJECT_TAG = '<script src="/overlay.js"></script>'

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        # Root ("") and "index.html" both resolve to the SPA entry document.
        if path in ("", ".", "index.html") and getattr(response, "status_code", 0) == 200:
            try:
                index_path = os.path.join(str(self.directory), "index.html")
                with open(index_path, "r", encoding="utf-8") as f:
                    html = f.read()
                if self._INJECT_TAG not in html:
                    if "</head>" in html:
                        html = html.replace(
                            "</head>", self._INJECT_TAG + "</head>", 1
                        )
                    else:
                        html = self._INJECT_TAG + html
                injected = Response(html, media_type="text/html")
                injected.headers["Access-Control-Allow-Origin"] = "*"
                return injected
            except Exception:
                return response
        return response


class WebSocketServer:
    """
    API server for Open-LLM-VTuber. This contains the websocket endpoint for the client, hosts the web tool, and serves static files.

    Creates and configures a FastAPI app, registers all routes
    (WebSocket, web tools, proxy) and mounts static assets with CORS.

    Args:
        config (Config): Application configuration containing system settings.
        default_context_cache (ServiceContext, optional):
            Pre‑initialized service context for sessions' service context to reference to.
            **If omitted, `initialize()` method needs to be called to load service context.**

    Notes:
        - If default_context_cache is omitted, call `await initialize()` to load service context cache.
        - Use `clean_cache()` to clear and recreate the local cache directory.
    """

    def __init__(self, config: Config, default_context_cache: ServiceContext = None):
        self.app = FastAPI(title="Open-LLM-VTuber Server")  # Added title for clarity
        self.config = config
        self.default_context_cache = (
            default_context_cache or ServiceContext()
        )  # Use provided context or initialize a new empty one waiting to be loaded
        # It will be populated during the initialize method call

        # Add global CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Include routes, passing the context instance
        # The context will be populated during the initialize step
        self.app.include_router(
            init_client_ws_route(default_context_cache=self.default_context_cache),
        )
        self.app.include_router(
            init_webtool_routes(default_context_cache=self.default_context_cache),
        )

        # Initialize and include proxy routes if proxy is enabled
        system_config = config.system_config
        if hasattr(system_config, "enable_proxy") and system_config.enable_proxy:
            # Construct the server URL for the proxy
            host = system_config.host
            port = system_config.port
            server_url = f"ws://{host}:{port}/client-ws"
            self.app.include_router(
                init_proxy_route(server_url=server_url),
            )

        # Mount cache directory first (to ensure audio file access)
        if not os.path.exists("cache"):
            os.makedirs("cache")
        self.app.mount(
            "/cache",
            CORSStaticFiles(directory="cache"),
            name="cache",
        )

        # Mount static files with CORS-enabled handlers
        self.app.mount(
            "/live2d-models",
            CORSStaticFiles(directory="live2d-models"),
            name="live2d-models",
        )
        self.app.mount(
            "/bg",
            CORSStaticFiles(directory="backgrounds"),
            name="backgrounds",
        )
        self.app.mount(
            "/avatars",
            AvatarStaticFiles(directory="avatars"),
            name="avatars",
        )

        # Mount web tool directory separately from frontend
        self.app.mount(
            "/web-tool",
            CORSStaticFiles(directory="web_tool", html=True),
            name="web_tool",
        )

        # Mount GIF assets used for action-overlay animations
        if not os.path.exists("gifs"):
            os.makedirs("gifs")
        self.app.mount(
            "/gifs",
            CORSStaticFiles(directory="gifs"),
            name="gifs",
        )

        # Serve the GIF-overlay script (injected into the frontend index.html).
        async def _serve_overlay_js(request):
            return FileResponse(
                "overlay.js",
                media_type="application/javascript",
                headers={"Cache-Control": "no-store"},
            )

        self.app.add_route("/overlay.js", _serve_overlay_js)

        # Temporary debug sink: the GIF overlay POSTs computed coordinates here
        # so they land in the backend log (used to calibrate model->screen math).
        async def _debug_log(request):
            try:
                raw = await request.body()
                with open("/tmp/gif_debug.txt", "ab") as fp:
                    fp.write(raw + b"\n")
            except Exception:  # noqa: BLE001
                pass
            return Response("ok")

        self.app.add_route("/debug-log", _debug_log, methods=["POST"])

        # Mount main frontend last (as catch-all). FrontendStaticFiles injects
        # the overlay script into index.html on the fly.
        self.app.mount(
            "/",
            FrontendStaticFiles(directory="frontend", html=True),
            name="frontend",
        )

    async def initialize(self):
        """Asynchronously load the service context from config.
        Calling this function is needed if default_context_cache was not provided to the constructor."""
        await self.default_context_cache.load_from_config(self.config)

    @staticmethod
    def clean_cache():
        """Clean the cache directory by removing and recreating it."""
        cache_dir = "cache"
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
            os.makedirs(cache_dir)

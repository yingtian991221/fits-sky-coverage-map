# Desktop launcher / EXE 与缓存

Windows builds contain `FITSSkyMap.exe` and `_internal`. Keep the entire folder together. No separate Python installation is required. The launcher opens the map in your default browser and manages a local Waitress service, restarting unexpected service exits up to three times. Closing it stops only the service it started. The default sky renderer now uses Aladin Lite v2 Canvas 2D rather than the v3 WebGL/WASM renderer. Packaging alone does not prevent browser failures.

默认在 EXE 所在目录创建 `data` 与 `tmp`。复用旧档案用 `FITSSkyMap.exe --home "F:\your-project"`；该目录应含现有 `data` 子目录，而非原始 FITS 目录。新用户直接双击后在网页添加照片目录。`--port` 可修改默认端口 8765。服务日志位于 `data/desktop-server.log`。

## Persistent cache / 磁盘缓存

DSS2 color tiles and Aladin Lite v2 and jQuery 3.7.1 are fetched through the local service and stored in `data/web-cache.sqlite`. Only successful responses are stored. Cached content is limited to 2 GiB with least-recently-used eviction. SQLite bookkeeping and reusable free pages can make the file somewhat larger. Cached objects need no remote connection. First visits to a new region or zoom level still need the network. No FITS pixels or local paths are sent to survey servers.

缓存按浏览区域与缩放级别逐步积累，不是完整全天离线星图，也未导入 NINA cache 格式。设置页可查看使用量。已有索引、解析结果、预览继续保留；未缓存的目标名称解析仍可能需要联网。

## Stability changes / 稳定性改动

Footprints are added in batches, with at most 500 nearby outlines drawn per viewport and a visible count. Zoom/filter to inspect others; spatial queries still use the full index. Group details omit full FITS headers, file rows expand in pages of 100, stale selection responses are ignored, and overlay updates pause during pointer drags. These reduce known load sources but do not establish the cause of every past crash.

## Building

Run `Setup.cmd`, then `powershell -ExecutionPolicy Bypass -File BuildExe.ps1`. The output is `dist/FITSSkyMap/`, using [PyInstaller one-folder mode](https://pyinstaller.org/en/stable/operating-mode.html). Private FITS, databases, configuration and caches are excluded. Distribute the whole output folder.

Tests: `python -m unittest test_archive test_portable test_desktop -v`.

## Validation (2026-10-17)

19 unit/integration tests passed. The packaged EXE served both an empty installation (zero files/roots) and an existing 44,627-file archive. An intentionally stopped owned service was restarted by the launcher with a new process ID. Thirteen real cached DSS/script resources were returned in a fresh test process with network access mocked to fail. Browser checks displayed the real survey through the cache and preserved rotated footprints. These are functional checks, not a long-duration crash-free guarantee. The distribution includes dependency-provided test fixtures but no personal FITS, archive database, or device/source settings.


## Dragging compatibility fix

After an Aw, Snap report, the default renderer was changed to Canvas 2D. Dragging pauses application overlay updates, release triggers a delayed refresh, and drag-release events do not issue accidental coordinate queries. Catalogue layers clear in one batch. The old engine’s coordinate grid threw on invalid projected points during adaptation; a separate grid now checks projection results and splits discontinuities. Sixty real pointer drags, including 36 in a roughly 400-footprint wide view, completed without a reported script error in the test page. This is not a guarantee against every browser/process crash.

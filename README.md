# FITS Sky Coverage Map / FITS 天空覆盖地图

[Portable installation validation](docs/portable-validation.md)

[中文使用说明](README.zh-CN.md) · [Configuration example](settings.example.json) · [Contributing](CONTRIBUTING.md)

**Build a sky coverage map from your own local FITS collection.** Add your imaging folders, index their headers, recover actual field boundaries, and search for previous observations around an object or coordinate. Useful for finding forgotten data, checking framing across imaging systems, and identifying possible mosaic overlaps.

This is a reusable local application and reference implementation. A new installation starts empty: no author's archive, instrument names, private paths, database, or example observations are loaded. Your FITS files stay on your computer and are read-only. Device names come from your FITS headers unless you explicitly configure a folder correction.

## Quick start — Windows

1. Install Python 3.10 or newer and enable **Add Python to PATH**.
2. Download the repository using GitHub's **Code → Download ZIP**, then extract it onto a drive with free space. Or clone it:

   ```powershell
   git clone https://github.com/yingtian991221/fits-sky-coverage-map.git
   cd fits-sky-coverage-map
   ```

3. Double-click **Setup.cmd**. It creates a project-local `.venv` and installs the Python dependencies. It does not install ASTAP or download a star database.
4. Double-click **OpenSkyArchive.cmd**. Open [127.0.0.1:8765](http://127.0.0.1:8765/). Closing the browser leaves the local server running; after reboot, run this launcher again. No automatic login/startup task is installed for new users.
5. Expand **数据目录与扫描** (Data folders and scan). Add your own absolute folder paths, select the roots, and click **扫描选中目录** (Scan selected folders). Start with a small folder to check your metadata and solver setup.

Manual installation:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Windows is the tested platform. The Python server can also be run with a virtual environment on other platforms, but those platforms and their ASTAP installations have not been validated. The current main interface is Chinese; first-run guidance, settings, and these instructions include English.

## From files to your sky map

### 1. Index your folders

The scanner recursively reads `.fits`, `.fit`, and `.fts` headers. It identifies Light/Dark/Flat/Bias, records available metadata, groups Light frames by equipment/session/framing, and retains files that cannot yet be mapped. Missing information stays unknown.

An existing celestial WCS is checked for completeness, pixel/world round-trip accuracy, plausible scale, and minimal pixel quality. Valid Light-frame WCS is adopted during scanning without ASTAP. RA/DEC pointing values alone are not a WCS. Files without a valid WCS appear in the target list but do not get confirmed map boundaries.

### 2. Recover missing boundaries (optional ASTAP)

Install [ASTAP and an appropriate star database](https://www.hnsky.org/astap.htm) separately if your images lack WCS. Reuse an existing installation where possible.

In **Settings / 设置**, set:

| Field | Meaning |
| --- | --- |
| Executable | Full path to `astap_cli.exe` or your ASTAP executable. Blank searches PATH and the usual Windows installation. `ASTAP_PATH` is also supported. |
| Star catalogue directory | Your installed star database directory. Blank leaves this to ASTAP. |
| Database abbreviation | For example `d50` or the abbreviation of your installed database. Blank does not force any specific database. |
| Timeout | Maximum time per representative frame, in seconds. |

Executable detection does not prove that a compatible star catalogue is present. Test your installation with a small real folder. The app passes `-d` and `-D` only when you supply these settings; it does not require a particular database family.

Enable **Solve representative frames** and scan. **Batch limit = 0** processes all eligible batches in the selected directories; a positive number limits batches per directory for a quick trial. Every selected batch starts with first/middle/last frames and is subdivided when solved framing changes. “All batches” still uses representative sampling; it does not solve every exposure. Failed frames remain in the review list. Individual retries are available through the CLI.

### 3. Explore your observations

- Search a name, decimal coordinates such as `83.82 -5.39`, or sexagesimal coordinates such as `05:35:17 -05:23:28`.
- Filter by equipment, filter, date, and evidence state. Select a target for totals across sessions, or a field for its particular batch.
- Boundaries use the real solved rotation and spherical projection. Click a field to inspect geometry and candidate overlaps.
- A coordinate match means that the **query point** lies in a representative frame, not that an extended target is fully covered.
- Raw acquisition time is separated by imaging system and filter. It is not equivalent image depth and not a guarantee of usable integration time.

Evidence states: **已解析代表帧** = solved representative frame; **抽样估算** = coverage estimated from agreeing samples; **待确认** = unconfirmed. A solver failure does not diagnose clouds, a closed roof, or poor focus.

### 4. Update incrementally

Run the same scan after adding images. Unchanged files and completed solutions are reused. An interrupted scan can be run again; committed index records persist. A missing source directory is reported without silently removing its records. Removing a root from the configuration stops future scans of that root; existing index entries remain. There is currently no archive-pruning UI.

Do not run separate CLI scans while a web scan is active. A running web job ends if its server process exits; completed database records survive, but the job itself is not a persistent queue.

## Optional configuration and labels

**Incorrect FITS equipment names:** use Settings to add a folder path and telescope display name. The rule covers that folder and descendants; the most specific path wins. The original header is preserved. There are no built-in observatory-specific aliases. Advanced users may supply increasing integer `focal_bins` in a rule in `data/settings.json` to group header focal lengths into bands. See [settings.example.json](settings.example.json) for the empty default structure.

**Object labels:** the survey is provided by Aladin Lite/DSS2 online. Optional Messier, NGC, Abell, LBN, and LDN centre-point lists can be downloaded explicitly:

```powershell
.\.venv\Scripts\python.exe build_catalogs.py
```

Without those lists, indexing and coordinate queries still work; name lookup can use CDS Sesame. Only the typed search name is sent to Sesame. FITS, paths, and pixels are not uploaded. Catalogue labels represent object centres, not object outlines. The map UI and survey imagery need internet access.

## Files, commands, and limitations

All writable application state is under this checkout:

| Location | Contents |
| --- | --- |
| `data/roots.json` | Your selected source folders |
| `data/settings.json` | Your solver settings and equipment corrections |
| `data/archive.sqlite` | File metadata, solutions, and scan records |
| `data/solutions/` | Local solver output and evidence |
| `data/previews/` | Raw-pixel sampled previews |
| `tmp/` | Temporary work |

The solver receives a project-local copy. Allow room for the largest frame plus previews and index growth. These directories are ignored by Git and never shipped as example data. Back up `data` to preserve your index; rebuilding from your original FITS is also possible.

```powershell
# Inside the activated virtual environment:
python scan_all.py
python archive.py scan "E:\Astro\session"
python archive.py sample-roots --per-root 0 --timeout 90
python archive.py sample-target M45 --timeout 90
python archive.py solve FRAME_ID --retry --timeout 90
```

The app is a local single-user prototype, not a network-hosted service. Current limits include two-dimensional FITS images (no XISF/compressed-FITS support), a 20° maximum footprint radius, discretely sampled boundary intersections, and heuristic processing-version/duplicate detection. Unknown processing versions can be mapped but are excluded from raw exposure totals. Recognized NINA/ASIAIR acquisition metadata is used for raw attribution; unfamiliar capture software may need an additional parser. DATE-LOC is preferred for local-date display; otherwise dates remain explicitly UTC. There is no calibration, stacking, mosaic processing, image registration onto the survey, or automatic quality classification.

## Reference implementation and tests

`archive.py` handles FITS/WCS, grouping, solving and geometry; `settings.py` holds installation configuration; `app.py` provides the local API; `static/` renders the map. See [CONTRIBUTING.md](CONTRIBUTING.md) for adaptation and test guidance.

```powershell
python -m unittest test_archive test_portable -v
```

The public tests generate small isolated FITS/WCS fixtures. They require neither the author's database nor ASTAP and do not load fixtures into your real index. These fixtures validate software behavior, not real solver accuracy.

MIT license for this project. Aladin Lite, ASTAP, survey imagery, and CDS catalogues belong to their respective providers and retain their own licenses/terms. They are not bundled here.

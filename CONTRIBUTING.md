# Adapting the project / 参考与贡献

This repository is intended to help observers build their own maps and adapt the implementation to their equipment. Issues and pull requests are welcome. Please do not post private image paths, credentials, full FITS headers containing location information, or raw observations unless you intend to share them.

本项目供不同用户建立自己的地图和参考修改。欢迎提交问题和改进；复现问题时优先使用去除个人信息的头字段片段或生成的小型夹具。

## Code map

| Module | Responsibility |
| --- | --- |
| `archive.py` | Header parsing, session/framing groups, quality screening, WCS geometry, ASTAP adapter, exposure accounting |
| `roots.py` | Per-installation source folders |
| `settings.py` | Validated solver settings and explicit directory-based equipment corrections |
| `app.py` | Loopback Flask API and background scan/solve jobs |
| `static/index.html`, `static/setup.js` | Aladin map, query UI, first-run guidance and settings |
| `catalogs.py`, `build_catalogs.py` | Optional compact object-centre lists |

## Development

Install `requirements.txt` in a virtual environment. Run `python app.py` and use a small directory of your own test frames. Run `python -m unittest test_archive test_portable -v` before proposing a change. Public tests must work from an empty checkout and must never rely on a particular observer's database, object counts, telescope names, or installed solver. Test generated images are software fixtures, not observational evidence.

When adding capture-software support, preserve raw header values and explain the evidence for raw/calibrated/stacked classification. Never infer confirmed coverage from a target name or pointing alone. Keep device corrections in user settings rather than adding global directory-name exceptions. If adjusting geometry, include tests for rotation, RA wrap, projection and containment. Any new solver must receive a local copy and have a timeout.

Default CI covers Windows/Python 3.12 without ASTAP. Real solver tests are performed locally with privately held images; report the solver version, catalogue, counts, and limitations without publishing the data automatically.

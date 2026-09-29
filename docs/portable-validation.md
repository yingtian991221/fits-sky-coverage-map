# Portable installation validation / 独立安装验证

Validated on Windows with Python 3.12, using a separate source copy in a directory
containing spaces and a newly created `.venv`. No archive database, source-folder
configuration, device overrides, previews, or label catalogue was copied from the
development installation.

## Results

- `Setup.ps1` installed the requirements successfully.
- `python -m unittest test_archive test_portable -v`: **15 passed**, none skipped.
  Tests generate isolated fixtures; they do not require the author's data or ASTAP.
- Empty first launch displayed zero files, no source folders, and the setup guide.
- Two real FITS copies from different cameras were added through the source-folder
  API, scanned and solved using a locally installed ASTAP with D50: **2 succeeded,
  0 failed**. This is the tested solver configuration, not a bundled dependency.
- Recovered centers and position angles matched their previous ASTAP solutions
  exactly. This checks reproducibility, not independent astrometric accuracy.
- Coordinate containment and intersection-candidate endpoints succeeded. The two
  sample fields are separated; positive intersection cases are tested with generated
  WCS fixtures, not claimed as real overlapping observations.
- The browser displayed both targets and their equipment, measured field size,
  orientation, representative-frame evidence, and exposure information. The settings
  dialog displayed the installation's own solver configuration.
- Repeated scanning reported two unchanged files and no duplicates. A fresh Python
  process retained the two records and configured source folder.
- SHA-256 checks confirmed original files and test copies were unchanged.

The real FITS, their paths, and the resulting database are private local validation
artifacts and are not distributed. This two-frame check does not establish that
every camera, FITS dialect, or observing session works. Multi-frame coverage remains
sampled unless every frame has its own valid solution.

中文摘要：已用无个人配置、无数据库的全新副本完成安装验证，15 项自动化测试通过；
另用两种相机的真实 FITS 各一张跑通添加目录、扫描、解析与查询，成功 2、失败 0。
重复扫描不重复入库，新进程保留索引，原片与测试副本哈希未变。真实数据不随仓库发布；
两帧验证不能代表所有设备和数据格式，多帧批次仍需区分实解与抽样估算。

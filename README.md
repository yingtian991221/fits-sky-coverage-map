# Historical Sky Coverage Archive / 历史天空覆盖档案

A local, read-only FITS index and sky map for astrophotography archives. It groups raw Light frames by actual session and framing, shows solved field boundaries on Aladin Lite's survey map, and keeps unsolved frames visibly unconfirmed. Raw FITS files never leave your computer.

本地 FITS 档案：按拍摄批次与构图整理 Light，使用真实 WCS 在 Aladin Lite 巡天底图上绘制历史视场。只有目标坐标或望远镜指向的照片会保留在索引中，但不会冒充已确认覆盖。

## 安装与启动（Windows）

需要 Python 3.10+。将项目放在**有足够空间的磁盘**，索引、预览和星场解析临时副本都会留在项目目录；原片只读。

```powershell
cd <项目目录>
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\OpenSkyArchive.cmd
```

浏览器访问 [http://127.0.0.1:8765/](http://127.0.0.1:8765/)；服务只监听本机。也可以运行 `python app.py` 前台启动。网页中的“数据目录与扫描”可添加一个或多个 FITS 文件夹，勾选后点击“扫描选中目录”。配置保存在 `data/roots.json`，不会加入 Git。扫描可中断后重做：未变化文件跳过 FITS 头解析，已有解保留。移除配置中的目录不会删除原始文件，也不会立即删除索引；要使已移除目录的旧记录不再显示，需手动清理索引（尚无网页清理功能）。

如果安装 [ASTAP](https://www.hnsky.org/astap.htm) 和适合自己视场的星表，可勾选“扫描后解析每目录的代表批次”。程序默认尝试系统 PATH 中的 `astap_cli`/`astap`，其次尝试 `C:\Program Files\astap\astap_cli.exe`；也可用环境变量 `ASTAP_PATH` 指定。当前星场解析命令使用 ASTAP 的 D50 星表配置；没有这套星表时请取消该选项，索引与头信息整理仍可用。每目录默认抽取两个批次的首、中、尾代表帧；其他批次仍可能待确认。不要把这一步理解为全库已完成星场解析。

命令行入口：`python scan_all.py` 扫描全部已配置目录；`python archive.py scan "E:\Astro\done"` 扫描单个目录；`python archive.py sample-roots --per-root 2 --timeout 90` 抽样代表帧。`增量扫描.ps1` 也支持 `-Root`。不要同时运行多个扫描进程。

## 能做什么

- 递归索引 `.fits`、`.fit`、`.fts`，记录 FITS 头、设备、滤镜、曝光、日期、尺寸、binning 和 WCS；Dark/Flat/Bias 与 Light 区分。按原始采集记录累计曝光，疑似重复与校准/叠加版本不重复计入。
- 使用有效 WCS 或 ASTAP 实际解的像素边界，不用屏幕轴对齐矩形代替旋转视场。跨 RA 0° 的包含和相交查询在天球坐标下完成。
- 左侧按设备、滤镜、日期、证据状态筛选；搜索目标名或 RA/Dec；点击视场查看各滤镜曝光、代表帧预览、文件路径及相交候选。几何相交只表示可能的拼接/包含，不保证可以合成。
- “已解析代表帧”“抽样估算”“待确认”分开显示。未解帧不画成已确认覆盖。不同成像系统的曝光时长分别列出，不换算所谓等效深度。
- 星图通过在线 Aladin Lite / DSS2 加载；坐标搜索离线可用。名称搜索在本机小目录无匹配时使用 CDS Sesame；不会上传 FITS、文件路径或图像像素。可运行 `python build_catalogs.py` 下载 Messier/NGC/Abell/LBN/LDN 的小型中心点目录到本机 `data`，用于分级标注（此缓存不随代码发布）。

某些 NINA/ASIAIR 文件头里的设备名称与实际镜筒不符。当前对目录名包含 `Gaoyazi_CAM_6200MM/scope_SR130APO`、`scope_sw200` 及 `140PH_cam_2600MCDuo1` 的档案有显示名称校正规则；FITS 原值仍保留在详情中，焦距不自动猜测。这些规则是源代码中的可选特例，其他用户不会自动获得同等的设备校正。

## 数据与限制

`data/archive.sqlite` 是持久化逐文件索引；`data/solutions` 保存解算证据；`data/previews` 保存本地抽样预览；`tmp` 保存解析临时副本。两目录被 `.gitignore` 排除。应用不提供上传原始 FITS 的接口。发布自己的 fork 前仍应检查 `git status`，确保没有自行添加的私有资料。

批次优先按设备、目标、观测夜、目录、binning、尺寸、处理版本和计划角度分开，再按指向/时间变化切段；同名目标的所有照片不会默认算成同一构图。代表帧的成功解析只能证明这些帧的实际边界；组内其他帧的覆盖仍属抽样估算。解析失败只进入待复核，不推断未开顶、云或失焦。

本版是本机单用户工具。扫描网页任务只在进程存活期间显示进度；服务重启后已写入 SQLite 的文件索引和解算记录仍在，重新扫描可继续。当前 ASTAP 命令在大视场/不同星表环境下可能需要调整 `archive.py` 的参数。

## 开发验证

```powershell
python -m unittest test_archive -v
```

真实观测数据、个人路径、数据库、扫描报告和本机缓存均不在公开仓库。测试中的小型 FITS/WCS 是临时数学夹具，不会被加入数据库。

## License

MIT. Aladin Lite、ASTAP、DSS2 与 CDS 目录由各自提供者维护，使用时遵循其条款；本仓库不包含它们的星表或原始巡天图像。

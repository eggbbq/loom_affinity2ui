# loom-affinity2ui

独立安装的 Affinity → LayaAir UI 导出库。保留组件规则、短图片名、九宫格、跨页面去重与事务发布，可在任意工作区通过 Python API 或 `affinity2ui` 命令使用。包内不包含业务工程、美术稿和生产导出资源，不读取原项目的 `.agents`、脚本或虚拟环境。

支持 Python 3.12+。原生 AF 读取与切图需要已经运行并开启本地 MCP 的 Affinity（`http://[::1]:6767/sse`）；自动打开文档目前仅支持 macOS。SDK 交换目录默认用户 Desktop，可以显式改为 Affinity 允许访问的目录。脚本读取已保存的文档，临时改变选择后恢复，不保存或改写 AF；运行导出不需要 LLM 或模型 token。

九宫格与最终缩放验证还需要 Node.js/npm、Google Chrome 和 LayaAir 3.4.1/3.4.2 对应引擎库。包不包含或下载 Laya 引擎和设计软件。

通过 `export`、`export-all`、`check` 或 `reoptimize` 的 `--engine-dir` 可指定引擎 JS 目录；导出时该选项同时用于基础九宫格验证和最终缩放验证。

## 安装发行包

正式发行渠道为 [GitHub Release v0.1.1](https://github.com/eggbbq/loom_affinity2ui/releases/tag/v0.1.1)，未发布到 PyPI。预制体序列化、布局验证、资源 metadata 和相似图去重由本库内部模块实现，不安装或导入 `psd2ui`、`psd-tools`。保留已有 UUID 命名空间、节点 ID 和组件规则，升级不会因为模块归属变化而重建资源身份。

九宫格来自独立的 [loom-image9grid v1.1.0](https://github.com/eggbbq/loom_image9grid/releases/tag/v1.1.0)，官方 wheel 保持原样，SHA256 固定为 `dc63c5401f01d1410d8a83a91e882c1fae9994a97752c35dffb66ad063345cf6`。算法命名空间 `ninegrid` 的唯一提供者为 `loom-image9grid==1.1.0`。升级旧环境时建议重新创建虚拟环境，避免旧版 psd2ui 内置的同名文件残留。

在线安装固定发行资产：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install \
  'https://github.com/eggbbq/loom_image9grid/releases/download/v1.1.0/loom_image9grid-1.1.0-py3-none-any.whl' \
  'https://github.com/eggbbq/loom_affinity2ui/releases/download/v0.1.1/loom_affinity2ui-0.1.1-py3-none-any.whl'
```

发布资产中的 `SHA256.json` 记录主包、源码包及 wheel bundle 的逐文件校验和。用于工程锁定时，应下载发行资产并同时校验固定 SHA256，不从开发分支或本机目录隐式加载。

macOS arm64 / CPython 3.12 可下载同一 Release 中的 `loom-affinity2ui-0.1.1-macos-arm64-cp312.zip`，解压后按下方离线安装方式使用；Node/npm 验证运行时仍需单独安装或使用本机缓存。

```sh
python3.12 -m venv .venv
# release/wheels 中提供主包、官方算法及当前构建平台的全部 Python 依赖。
.venv/bin/python -m pip install --no-index --find-links /path/to/release/wheels loom-affinity2ui==0.1.1
.venv/bin/affinity2ui --version
.venv/bin/affinity2ui doctor
```

也可单独安装两个纯 Python wheel，让 pip 从已有镜像解析其常规依赖：

```sh
python -m pip install loom_image9grid-1.1.0-py3-none-any.whl loom_affinity2ui-0.1.1-py3-none-any.whl
```

主包与算法 wheel 是跨平台的 Python 包；离线 bundle 中 NumPy/Pillow 等二进制 wheels 对应打包时的 Python 和平台。其它环境需要重新下载适用的依赖 wheels。

安装验证运行时一次：

```sh
affinity2ui setup-runtime
```

Node 依赖安装到用户缓存的 `loom-affinity2ui/runtime`，不写 `site-packages`。可通过 `AFFINITY2UI_CACHE_DIR` 改变缓存根，或设置 `AFFINITY2UI_PLAYWRIGHT_MODULE` 指向已有 `playwright/index.js`。`doctor` 只报告 Python/Node 组件及缓存状态，不连接设计软件，也不把 Node 可用等同于完整引擎验收。

## 工作区与命令

安装包目录与工作目录完全分开。`--workspace` 默认为当前目录；配置和全部相对路径以工作区为基准。`--config` 仅选择配置文件，不隐式改变工作区。导出前需有真实的 LayaAir 工程，例如工作区下的 `client/`。

```sh
affinity2ui init --workspace /path/to/game
affinity2ui export art/ui/pages/LoginPanel.af --workspace /path/to/game --plan
affinity2ui export art/ui/pages/LoginPanel.af --workspace /path/to/game
affinity2ui export-all --workspace /path/to/game
affinity2ui check --workspace /path/to/game
```

`init` 创建示例 `export_all_ui.toml` 与源目录，不创建游戏工程，也不覆盖已有配置。源页规范保持独立 PascalCase Group，直属 `bg` 和 `content`；批量扫描默认 `art/ui/pages/*.af`。显式单文件输入可在工作区外，仍受组件结构检查。`--plan` 只采集结构并输出计划，不写项目资源；它仍需要 Affinity 打开或读取源文件。

配置分为 `paths`、`export`、`layout`、`checks`，可修改工程、资源、源文件、记录、报告、九宫格模式与名称忽略规则。配置示例作为包资源随 wheel/sdist 安装。命令行显式选项优先配置；页面对齐 JSON 再按每轴页面配置、默认配置、自动计算解析。`auto` 可明确覆盖指定对齐。

```sh
affinity2ui export Task.af --workspace /path/to/game --content-align-x center --content-align-y bottom
affinity2ui export Task.af --workspace /path/to/game --button-down-effect down-scale
affinity2ui export Task.af --workspace /path/to/game --no-pixel-grid
affinity2ui export Task.af --workspace /path/to/game --export-only
```

`--export-only` 明确跳过九宫格和 WebGL 验证，仍检查资源与引用；不能将它作为完整优化验收。`--no-dedupe-images` 关闭合并，但仍先恢复旧共享依赖，保护其它页面。`--already-open` 使用已打开的源文档，不调用系统自动打开命令。

## Python API

```python
from affinity2ui.api import export_sources

result = export_sources(
    ["art/ui/pages/LoginPanel.af"],
    workspace="/path/to/game",
    project="client",
    records_dir="out/affinity-export",
    dedupe=0.99,
    pixel_grid=True,
    button_down_effect="dark",
)
```

`export_all(workspace=..., sources_dir=...)` 使用相同事务。API import 不连接 Affinity、不切换 cwd、不修改 `sys.argv`。执行期间为兼容后端初始化，在锁保护下暂时选择工作区，成功或异常后恢复原 cwd；同一进程调用串行执行。并发处理多个工作区建议使用独立进程，调用方其它线程也应避免自行修改进程 cwd。

## 保留的 UI 和资源规则

- 原图片名后拼 `@` 与完整相对路径 BLAKE2b64/Base36 哈希，默认 13 位小写字母数字；跨所有功能检测碰撞，仅延长新路径名称。完整路径与名称映射保存在工程外清单。
- 图片平铺于 `ui/images/`，预制体平铺于 `ui/prefabs/`，配套 `.meta` 保留 UUID、采样和九宫格，纹理类型为精灵纹理 `textureType=2`。预制体使用 `res://UUID`。
- 绝对边界像素量化默认开启；页面 bg 宽高关系、content 几何中心与贴边判断、参数优先级保持原规则。
- 按钮绑定 title/icon，默认按下变暗；缩放效果使用中心锚点并补偿坐标。switch/tab 为原生 Check 和 on/off 显隐，checkbox 只切 on，均无动画。tabs 组单选仍仅记录设计约束，未添加额外运行时协调。
- 输入框保留外层 bg，title 转为全父尺寸 GTextInput，以 padding 保持原有效文本区域，placeholder 进入 prompt。
- list/content 为实际 GList，首 item 为模板，Demo 数量来自设计，拖动和裁切启用，滚动条隐藏。列表装饰脚本在需要时安装到项目 `src/ui`。
- 九宫格保留 1px 中心和采样保护，支持单轴与双轴，所有优化受 CPU 和真实 LayaAir/Chrome WebGL 误差预算约束，不放宽质量阈值。
- 支持可选项目 `src/ui/prefab-bindings.json` 恢复业务 runtime 和字段；库没有内置任何游戏面板或业务脚本。

## 事务、去重和维护

单页与整批均在工程外暂存：依赖恢复 → 切图与组件转换 → 九宫格及基础引擎验证 → 独立跨页面去重 → 最终资源与缩放检查 → 一起提交资源、记录及必要脚本。失败不发布暂存，源文件或目标并发变化时停止。生产工程外的 `out/affinity-export` 要持续保留；其中包含清单、原图、共享别名和 UUID 恢复依据。

```sh
affinity2ui dedupe --workspace /path/to/game
affinity2ui migrate --workspace /path/to/game          # 仅预览
affinity2ui migrate --workspace /path/to/game --apply
# 重优化报告必须与主导出记录分开，参数必填。
affinity2ui reoptimize client/assets/ui/images/bg@xxx.png --workspace /path/to/game \
  --records-dir out/repair-background --original-records out/affinity-export/Task/export-records/ninegrid
```

跨页面优先保留旧图，同步改写识别到的预制体图片引用；未知或脚本路径消费者仍受保护。下次重导先恢复独立原图，避免一个页面修改共享源导致其它页面图像变化。重优化拒绝覆盖主导出记录。图片命名、引用分析、共享状态、优化适配和事务分别维护；CLI 只编排模块。

## 构建与发布边界

```sh
python -m pip install build wheel setuptools
python scripts/build_release.py --bundle-dependencies
python -m unittest discover -s tests -p 'test_*.py'
```

`dist/` 生成主 wheel 和 sdist；`release/wheels/` 放主 wheel、官方算法与平台依赖，`release/SHA256.json` 记录校验和。构建前会清理这些生成目录，避免旧依赖混入发行；算法来源位于 `vendor/image9grid.json`。构建不提交代码、不推送 Git、不上传 PyPI。

本仓库与发行资产按 LICENSE 中的专有条款提供，并未授予开源许可。内部序列化和通用辅助模块由原有已验证快照移植，来源及原始文件 SHA256 记录在 `vendor/prefab-origin.json`；不包含 PSD 读取器。官方算法 wheel 的来源、版本和 SHA 见 `vendor/image9grid.json`，其许可声明以官方发行内容为准，具体见 `vendor/THIRD_PARTY_LICENSES.txt`。源码包可独立重建主 wheel，并自带官方算法 wheel 供安装。旧版 v0.1.0 的 tag 和资产保留，不覆盖历史发行。

# spriteforge（游戏序列帧工具，v1）

把一段短视频变成游戏可用的序列帧：抽帧 → AI 抠图 → 轻度时序平滑 →
按透明区域裁剪 → 合成 Sprite Sheet，并输出 Unity 友好的索引 JSON。

## Web 界面（推荐，跨平台、一键部署）

Web 界面和命令行用的是同一套处理流程（抽帧、BiRefNet 抠图、时序平滑、
合图），只是多了一个浏览器操作界面：拖入视频、调参数、看进度、
预览合图和逐帧动画、一键导出。适合本机或局域网使用；**v1 没有登录
鉴权，不要直接把 8000 端口暴露到公网**。

### 一键部署（Docker）

```bash
docker compose up -d
# 然后打开 http://localhost:8000
```

停止：`docker compose down`。任务上传和输出保存在项目下的 `jobs/` 目录。

### 一键部署（Docker，GPU 版，NVIDIA 独显）

Windows 上需要 Docker Desktop + WSL2 后端 + 主机上支持 WSL2 的 NVIDIA 驱动
（50 系显卡建议驱动 570+，对应 CUDA 12.8）；Linux 本机需要主机驱动 +
NVIDIA Container Toolkit。先验证 GPU 透传：

```bash
docker run --rm --gpus all nvidia/cuda:12.8.0-runtime-ubuntu22.04 nvidia-smi
```

能看到显卡后，再用 GPU 版配置启动（它用 `Dockerfile.gpu`，CUDA 12.8 基础镜像，
并把 CPU 版 `onnxruntime` 换成 `onnxruntime-gpu`；抠图代码本来就会优先用
CUDA，GPU 不可见时自动回落 CPU，不会直接报错）：

```bash
docker compose -f docker-compose.gpu.yml up -d --build
# 然后打开 http://localhost:8000
```

停止：`docker compose -f docker-compose.gpu.yml down`。注意：GPU 版镜像比 CPU 版
大很多，首次构建和首次运行下载约 1GB 模型都需要时间。

### 本地运行（不使用 Docker）

```bash
pip install -r requirements.txt
spriteforge-web
# 或：python -m spriteforge.web_app --host 127.0.0.1 --port 8000
# 然后打开 http://127.0.0.1:8000
```

GPU 机器上本地运行时，按安装一节把 `onnxruntime` 换成与 CUDA/驱动
匹配的 `onnxruntime-gpu`，速度会快很多；默认 Docker 镜像是 CPU 版，
GPU 版见上面一节。

### Web 界面功能

- 导入：拖放或文件选择上传视频，上传后可直接预览原视频；单个文件上限 200MB
- 参数：fps（默认 12）、列数（默认 6）、间距（默认 4）、模型（默认 birefnet-general）、
  输入上限（默认 720px）、单帧目标尺寸（可选）、时序平滑开关（默认开）、
  边缘去溢色开关（默认开，强度默认 1.0，幕布颜色可选绿/蓝/红/青/品红/黄或自定义）；提交过的参数会自动记住
  （存在浏览器本地，下次打开直接沿用，换浏览器时第一次先用最近一次历史任务的参数，
  也可点“恢复默认参数”回到默认值）
- 进度：轮询任务状态（queued / processing / completed / failed），失败原因直接显示在页面上
  （如缺少 ffmpeg、模型首次下载失败等），而不是只打在控制台；加载模型时会明确提示
  “首次使用需下载约 1 GB、进度会在 20% 停留一段时间”，失败后开始按钮恢复可用，
  并可点“重新生成”用同一视频和参数直接再跑一次
- 预览：Sprite Sheet 大图、按 fps 播放的逐帧动画（播放/暂停/拖动进度条）、逐帧缩略图网格
- 导出：下载 sprite.png、index.json，或下载 ZIP（合图 + 索引 + 全部单帧）
- 历史记录：每次任务的参数和结果以 job.json 保存在 jobs/ 下，服务重启后仍可查看；
  历史列表里可查看旧任务、下载合图/ZIP，或手动删除单个任务（连同原视频、单帧、合图一起删掉）

### Web API（供脚本调用）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | Web 界面 |
| GET | `/api/health` | 健康检查 |
| POST | `/api/jobs` | multipart 上传视频 + 表单参数（fps、columns、spacing、model、max_size、target_size、temporal_smoothing、despill、despill_strength、despill_edge_width），返回 `{"id": ...}`（202） |
| GET | `/api/jobs/{id}` | 任务状态、进度、错误、帧列表 |
| GET | `/api/jobs/{id}/sprite.png` | 合图下载 |
| GET | `/api/jobs/{id}/index.json` | Unity 索引下载 |
| GET | `/api/jobs/{id}/frames/{name}` | 单帧 PNG 下载 |
| GET | `/api/jobs/{id}/export.zip` | ZIP 导出（合图 + 索引 + 单帧） |

任务状态只保存在内存里，服务重启后旧任务记录会丢失（磁盘上的 `jobs/` 文件仍在，
但需要重新提交任务）。可通过环境变量 `SPRITEFORGE_JOBS_DIR` 修改任务存储目录。

## 功能

- 输入短视频（典型：1–3 秒，720×720 及以下分辨率）
- 输入上限 **720px**：已在上限内的原样使用、不放大；超过上限的按比例缩小到上限内，不压扁、不裁剪
- 默认 **12 fps** 抽帧（可用 `--fps` 修改）
- 用 **BiRefNet-general**（rembg）抠图，保留**软 alpha**，不做二值硬切
- 抠图后默认做**边缘去溢色**：只处理轮廓附近的幕布溢色（幕布主色压到其他通道最大值），不碰内部，
  绿幕源的绿边可去掉（可用 `--no-despill` 关闭，`--despill-strength` 调强度，`--despill-edge-width` 调边缘宽度，
  `--despill-color` 选幕布颜色：green/blue/red/cyan/magenta/yellow 或自定义 `#RRGGBB`；白/灰/黑色幕布无颜色溢色可去）
- 对 alpha 通道做 3 帧滑动平均，减轻逐帧闪烁（可用 `--no-temporal-smoothing` 关闭）
- 抠图后按 alpha bbox 裁剪：默认用**全局统一裁剪框**（所有帧的并集框），
  这样逐帧 mask 噪点不会让角色在格子里上下左右抖动，且目标尺寸下的缩放比例全帧一致；
  可用 `--crop-mode per-frame` 恢复旧的逐帧单独裁剪（可能抖动）
- 可选 `--target-size` 统一单帧尺寸
- 输出单张序列帧 PNG + Sprite Sheet PNG + `index.json`

## 系统要求

- Python 3.11+
- **FFmpeg**（提供 `ffmpeg` 和 `ffprobe`，且在 PATH 中）；缺失时程序会明确报错，不会静默失败
- 显卡：推荐 RTX 5060 等 NVIDIA GPU（需 `onnxruntime-gpu`，见安装）；没有 GPU 也能在 CPU 上跑，只是慢很多
- 首次运行需要联网下载 BiRefNet-general 模型权重（约 1 GB），之后可离线使用

## 安装

```bash
cd spriteforge
pip install -r requirements.txt

# 有 NVIDIA GPU 时（按你的 CUDA/驱动版本选 onnxruntime-gpu 版本）：
pip uninstall -y onnxruntime
pip install onnxruntime-gpu
# 注意：不要同时装 onnxruntime 和 onnxruntime-gpu
```

## 使用

```bash
# 基本用法
python -m spriteforge --input video.mp4 --output out_dir

# 常用选项
python -m spriteforge --input video.mp4 --output out_dir \
  --fps 12 --columns 6 --spacing 4 \
  --model birefnet-general

# 关闭时序平滑、统一单帧为 512x512
python -m spriteforge --input video.mp4 --output out_dir \
  --no-temporal-smoothing --target-size 512x512
```

从项目根目录（`spriteforge/`）运行 `python -m spriteforge`。也可以先
`pip install -e .`（如有需要再补 pyproject 配置），但 v1 不依赖安装步骤。

### 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--input` | 必填 | 输入视频文件 |
| `--output` | 必填 | 输出目录 |
| `--fps` | `12` | 抽帧帧率 |
| `--columns` | `6` | Sprite Sheet 列数（按行优先排列） |
| `--spacing` | `4` | 单元格之间的像素间距 |
| `--model` | `birefnet-general` | rembg 模型名，可换 `birefnet-general-lite`、`birefnet-portrait`、`u2net` 等 |
| `--no-temporal-smoothing` | 关闭 | 关闭 3 帧 alpha 平滑 |
| `--crop-mode` | `union` | 裁剪模式：`union`（全局统一框，防抖动）或 `per-frame`（逐帧单独裁剪，旧行为） |
| `--no-despill` | 关闭 | 关闭边缘去溢色 |
| `--despill-strength` | `1.0` | 去溢色强度 0-1 |
| `--despill-edge-width` | `3` | 去溢色边缘宽度（像素） |
| `--despill-color` | `green` | 幕布颜色：green/blue/red/cyan/magenta/yellow 或自定义 `#RRGGBB` |
| `--target-size` | 不指定 | 单帧目标尺寸，如 `512x512`；不指定时以最大裁剪尺寸为准 |
| `--max-size` | `720` | 输入单边上限像素；低于上限不放大，超过上限按比例缩小 |

## 输出结构

```
out_dir/
  sprite.png      # Sprite Sheet（透明底 PNG）
  index.json      # 帧索引
  frames/
    frame_00000.png
    frame_00001.png
    ...
```

`frames/` 里的单张抠图 PNG 对游戏同样有用：高清单帧直接可用，
不必只依赖合图。

### index.json 格式（Unity 友好）

```json
{
  "tool": "spriteforge",
  "version": "1.0",
  "texture": "sprite.png",
  "sheet_size": {"w": 4348, "h": 4348},
  "frame_size": {"w": 720, "h": 720},
  "columns": 6,
  "rows": 6,
  "spacing": 4,
  "fps": 12,
  "frames": [
    {"name": "frame_00000", "index": 0, "x": 0, "y": 0, "w": 720, "h": 720,
     "unity_x": 0, "unity_y": 3628, "pivot": {"x": 0.5, "y": 0.5}, "t": 0.0}
  ]
}
```

其中 `t` 是该帧的时间戳（秒），`x/y/w/h` 是该帧在合图中的位置和尺寸（左上角原点）。
`unity_x/unity_y` 是 Unity 的左下角原点坐标，可直接用于 `Sprite.Create` 或
TextureImporter 的 sprite rect，`pivot` 默认为中心（0.5, 0.5）。

在 Unity 中使用时，把 `sprite.png` 导入为 Sprite（Multiple），或按
`index.json` 的 `unity_x/unity_y/w/h` 在运行时用 `Sprite.Create(texture, rect, pivot)`
逐帧创建 Sprite，再按 `fps` / `t` 做动画播放。不再要求兼容 FrameRonin 的索引格式。

## 输入规则：720 及以下，不放大、不压扁、不裁剪

- 输入已经是 720×720 及以下：原样使用，不放大、不重编码（除非需要抽帧）。
- 输入超过 720：按比例缩小到单边不超过 720，宽高比不变，不压扁、不裁剪。
- 抠图后仍按 alpha bbox 二次裁剪，只保留角色本体。


## 模型与授权说明

- 默认模型 **BiRefNet-general**，不要默认使用 RMBG-2.0：后者为
  非商业授权，商业游戏使用需要向 BRIA 购买授权。
- 换模型前请自行确认该模型权重的授权；工具本身的许可证见 `LICENSE`（MIT），
  不代表模型权重的授权。

## 限制（v1 已知）

- 这是逐帧图片抠图 + 轻度 alpha 平滑，不是真正的视频抠图模型
  （如 RVM / VRMBG）。快速运动、半透明材质仍可能有轻微闪烁，
  关键帧建议人工检查。
- Web 任务状态不持久化（见 Web 界面一节）；v1 有意保持小而简单，无 Redis、无登录鉴权。
- 输入视频过长、帧数过多时，内存占用会随帧数增长；v1 面向 1–3 秒短视频。
- 首次运行下载模型需要网络；模型缓存位置由 rembg/onnxruntime 决定。

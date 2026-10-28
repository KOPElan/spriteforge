# spriteforge（游戏序列帧工具，v1）

把一段短视频变成游戏可用的序列帧：抽帧 → AI 抠图 → 轻度时序平滑 →
按透明区域裁剪 → 合成 Sprite Sheet，并输出 Unity 友好的索引 JSON。

## 功能

- 输入短视频（典型：1–3 秒，720×720 及以下分辨率）
- 输入上限 **720px**：已在上限内的原样使用、不放大；超过上限的按比例缩小到上限内，不压扁、不裁剪
- 默认 **12 fps** 抽帧（可用 `--fps` 修改）
- 用 **BiRefNet-general**（rembg）抠图，保留**软 alpha**，不做二值硬切
- 对 alpha 通道做 3 帧滑动平均，减轻逐帧闪烁（可用 `--no-temporal-smoothing` 关闭）
- 抠图后按 alpha bbox 裁剪，可选 `--target-size` 统一单帧尺寸
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
- 任务状态不持久化，纯命令行工具，无 Web 界面、无 FastAPI（v1 有意保持小而简单）。
- 输入视频过长、帧数过多时，内存占用会随帧数增长；v1 面向 1–3 秒短视频。
- 首次运行下载模型需要网络；模型缓存位置由 rembg/onnxruntime 决定。

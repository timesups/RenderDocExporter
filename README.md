# RenderDoc Exporter

RenderDoc 扩展：从当前选中的 **Draw Call（EID）** 读取 VS Input 顶点数据，导出为 **FBX** 或 **OBJ** 模型。

## 功能概览

- 支持 FBX（二进制 7.5）与 OBJ（多 UV 通道分文件）导出
- 可配置顶点属性映射（Position / Normal / Tangent / Color / UV）
- 每个 VS Input 可单独选择 **Float / UInt / Int** 解码方式
- 多种坐标系预设，适配 OpenGL、Maya、Blender、Unreal 等 DCC / 引擎
- 统一缩放、反转法线、反转绕序、垂直翻转 UV
- 映射、解码方式与导出选项自动缓存，下次打开对话框自动恢复

## 环境要求

- RenderDoc **≥ 1.4**（扩展 API v1）
- FBX 导出需将 **aspose-3d** 库放到扩展根目录的 `aspose/` 下

## 安装

1. 将整个 `RenderDocExporter` 目录放到 RenderDoc 扩展目录，例如：
   - Windows: `%APPDATA%\qrenderdoc\extensions\RenderDocExporter`
2. 若需 FBX 导出，按项目说明配置 `aspose/` 依赖
3. 在 RenderDoc 中打开 **Tools → Extension Manager**，启用 **Renderdoc Exporter**

> 更新扩展代码后建议 **完全重启 RenderDoc**（不要仅 Reload），以免热重载残留旧模块导致导入失败。

## 使用方法

1. 在 **Event Browser** 或 **Mesh Preview** 中选中一条 **Draw Call**
2. 右键菜单选择 **导出为模型**
3. 在对话框中：
   - 将各 VS Input 属性映射到 Position、Normal、UV 等语义
   - 为每个属性选择 **解码方式**（Float / UInt / Int，默认 Float）
   - 选择坐标系预设、统一缩放及法线 / 绕序 / UV 选项
4. 点击 **确认**，选择保存路径（`.fbx` 或 `.obj`）
5. 等待进度条完成

> 仅支持非实例化的 VS Input；当前 EID 须为有效绘制且含索引数据。

## 导出设置

### 数据映射与解码

每个 VS Input 对应一行配置：

| 列 | 说明 |
|----|------|
| 属性名 | RenderDoc 报告的 VS Input 名称 |
| 语义映射 | None / Position / Normal / Tangent / Color / UV |
| 解码方式 | Float / UInt / Int（默认 **Float**） |

**解码方式说明：**

| 模式 | 行为 |
|------|------|
| **Float** | 按 RenderDoc 顶点格式自动解码（Float、UNorm、SNorm 等） |
| **UInt** | 强制按无符号整型读取，并以 HLSL `asfloat` 位模式写入 float |
| **Int** | 强制按有符号整型读取，直接导出为 float 数值 |

常见场景：UNorm8 颜色（如 `155/255 ≈ 0.608`）应使用 **Float**；若缓冲区中存的是需用 `asuint`/`asfloat` 还原的整型位模式，则选 **UInt**。

### 坐标系预设

相对 D3D VS Input 常见 **左手 Y-up** 对象空间：

| 预设 id | 说明 | 变换 `(x, y, z) →` |
|---------|------|-------------------|
| `opengl`（默认） | OpenGL 右手 Y-up | `(x, y, -z)` |
| `maya` | Maya 右手 Y-up | `(x, y, -z)` |
| `blender` | Blender 右手 Z-up | `(x, -z, y)` |
| `unreal` | Unreal 左手 Z-up | `(x, z, y)` |
| `d3d_raw` | 原数据，不转换 | `(x, y, z)` |
| `legacy_z` | 旧版 Z 轴向上（兼容缓存） | `(y, -x, z)` |

- **位置**：坐标系变换后乘 **统一缩放**
- **法线 / 切线**：仅坐标系变换，不缩放

### 其他选项

| 选项 | 说明 |
|------|------|
| 反转法线 | 常见 D3D 与 OBJ 查看器手性不一致时建议开启 |
| 反转三角形绕序 | 与反转法线配合修正背面剔除 |
| 垂直翻转 UV | 对 V 做 `1 - v` |
| 统一缩放 | 仅作用于顶点位置，默认 `1.0` |

## 设置缓存

确认导出后，配置写入扩展根目录的 `export_mapping_cache.json`（运行时生成，不纳入 git）。

示例：

```json
{
  "version": 1,
  "header_mappings": {
    "POSITION": "Position",
    "NORMAL": "Normal"
  },
  "export_settings": {
    "coord_preset": "opengl",
    "coord_preset_label": "OpenGL（右手 Y-up）",
    "uniform_scale": 1.0,
    "flip_normals": true,
    "flip_winding": true,
    "flip_uv_v": false,
    "header_decode_modes": {
      "POSITION": "float",
      "COLOR": "float"
    }
  }
}
```

## 顶点解码

`csv_to_model/vertex_decode.py` 负责按顶点格式解包；用户可在对话框中为每个属性覆盖解码方式。

**Float 模式（默认）** 按 RenderDoc `compType` 自动选择路径：

- `Float` → 按浮点解包
- `UNorm` / `UNormSRGB` → 归一化到 `[0, 1]`
- `SNorm` → 归一化到 `[-1, 1]`
- `UInt` → `asfloat` 位模式
- `SInt` → 有符号整型转 float
- 打包格式（R10G10B10A2、R5G6B5 等）→ 对应语义解码

**UInt / Int 模式** 忽略格式语义，强制按整型路径解码（适用于手动纠正误读）。

## 项目结构

```
RenderDocExporter/
├── __init__.py                  # 扩展入口，菜单注册与导出流程
├── extension.json               # 扩展元数据
├── README.md
├── export_mapping_cache.json    # 用户映射与导出设置缓存（运行时生成）
├── csv_to_model/
│   ├── mesh_from_eid.py         # 从 EID 读取 VS Input 网格
│   ├── vertex_decode.py         # 顶点格式解码（compType + 手动覆盖）
│   ├── exporter_dialog.py       # 导出配置对话框与缓存
│   ├── util.py                  # Vertex / ExportConfig / 坐标变换 / 解码模式
│   ├── fbx_exporter.py          # FBX 写入（Aspose.3D）
│   ├── obj_exporter.py          # OBJ 写入
│   └── exprorter.py             # 兼容桩（热重载用，逻辑已迁至 mesh_from_eid）
└── aspose/                      # FBX 依赖（需自行放置，不纳入 git）
```

## 已知限制

- 不支持实例化顶点属性（`perInstance`）
- FBX 顶点属性均为 float；大于 32 位的整型需自行拆分通道
- 扩展热重载可能加载旧版 Python 模块；更新后请重启 RenderDoc

## 作者

zcx \<zcxtimesup@gmail.com\>

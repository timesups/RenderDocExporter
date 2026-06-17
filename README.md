# RenderDoc Exporter

RenderDoc 扩展：从当前选中的 **Draw Call（EID）** 读取 VS Input 顶点数据，导出为 **FBX** 或 **OBJ** 模型。

## 功能概览

- 通过 Replay API 直接解码顶点缓冲与索引，不再依赖 Mesh Preview 表格
- 支持 FBX（二进制 7.5）与 OBJ（多 UV 通道分文件）导出
- 可配置顶点属性映射（Position / Normal / Tangent / Color / UV）
- 多种坐标系预设，适配 OpenGL、Maya、Blender、Unreal 等 DCC / 引擎
- 统一缩放、反转法线、反转绕序、垂直翻转 UV
- 映射与导出选项自动缓存，下次打开对话框自动恢复

## 环境要求

- RenderDoc **≥ 1.4**（扩展 API v1）
- FBX 导出需将 **aspose-3d** 库放到扩展根目录的 `aspose/` 下（见 `.gitignore`，该目录不纳入版本库）
- 内置 Python 约为 3.6，请勿使用 `from __future__ import annotations` 等新语法

## 安装

1. 将整个 `RenderDocExporter` 目录放到 RenderDoc 扩展目录，例如：
   - Windows: `%APPDATA%\qrenderdoc\extensions\RenderDocExporter`
2. 若需 FBX 导出，按项目说明配置 `aspose/` 依赖
3. 在 RenderDoc 中打开 **Tools → Extension Manager**，启用 **Renderdoc Exporter**
4. 修改代码后可在 Extension Manager 中 **Reload** 热重载

## 使用方法

1. 在 **Event Browser** 或 **Mesh Preview** 中选中一条 **Draw Call**
2. 右键菜单选择 **导出为模型**
3. 在对话框中：
   - 将各 VS Input 属性映射到 Position、Normal、UV 等语义
   - 选择坐标系预设、缩放及法线 / 绕序 / UV 选项
4. 点击 **确认**，选择保存路径（`.fbx` 或 `.obj`）
5. 等待进度条完成

> 仅支持非实例化的 VS Input；当前 EID 须为有效绘制且含索引数据。

## 导出设置

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

### 设置缓存

确认导出后写入扩展根目录 `export_mapping_cache.json`（已加入 `.gitignore`），包含：

- `header_mappings`：属性名 → 语义类型
- `export_settings`：`coord_preset`、`coord_preset_label`、`uniform_scale`、`flip_normals`、`flip_winding`、`flip_uv_v` 等

坐标系下拉框使用 ASCII 预设 id（`opengl`、`blender` 等），右侧标签显示中文说明，以避免 RenderDoc MiniQt 对 Unicode 下拉项读写不稳定的问题。

## 顶点解码

`csv_to_model/vertex_decode.py` 负责按顶点格式解包：

1. **优先按 Float** 解包（含 Regular 与 R10G10B10A2、R11G11B10 等打包格式）
2. 若结果为 **NaN / Inf**，回退为 **UInt**
3. UInt 回退使用 **HLSL `asfloat` 位模式** 写入 float，便于在 FBX 导入后于顶点着色器中用 `asuint()` 还原整型

```hlsl
// 例：整型 id 导出到顶点色 COLOR0
uint id = asuint(input.color.r);
```

> UInt 数据请映射到 Color 等通道，不要映射到 Position / Normal（坐标变换会破坏位模式）。

## 项目结构

```
RenderDocExporter/
├── __init__.py              # 扩展入口，菜单注册与导出流程
├── extension.json           # 扩展元数据
├── README.md
├── csv_to_model/
│   ├── mesh_from_eid.py     # 从 EID 读取 VS Input 网格
│   ├── vertex_decode.py     # 顶点格式解码（Float → UInt 回退）
│   ├── exporter_dialog.py   # 导出配置对话框与缓存
│   ├── util.py              # Vertex / ExportConfig / 坐标变换
│   ├── fbx_exporter.py      # FBX 写入（Aspose.3D）
│   ├── obj_exporter.py      # OBJ 写入
│   └── exprorter.py         # 兼容桩（热重载用，逻辑已迁至 mesh_from_eid）
└── aspose/                  # FBX 依赖（需自行放置，不纳入 git）
```

## 已知限制

- 不支持实例化顶点属性（`perInstance`）
- 不支持从 Mesh Preview 表格导出（旧版逻辑已移除）
- FBX 顶点属性均为 float；大于 32 位的整型需自行拆分通道
- `legacy_z` 等不在下拉列表中的预设仍可从缓存加载，但界面可能显示默认项

## 作者

zcx \<zcxtimesup@gmail.com\>

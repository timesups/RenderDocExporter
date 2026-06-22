# RenderDoc Exporter

RenderDoc 扩展（**Renderdoc Exporter** v1.1）：从当前选中的 **Draw Call（EID）** 经 Replay API 读取 **VS Input** 顶点数据，导出为 **FBX** 或 **OBJ** 模型。

## 功能概览

- 支持 **FBX**（二进制 7.5，Aspose.3D）与 **OBJ**（多 UV 通道分文件）导出
- 可配置顶点属性语义映射（Position / Normal / Tangent / Color / UV）
- 每个 VS Input 可单独选择 **Float / UInt / Int** 解码方式（默认 Float）
- 坐标系预设：OpenGL、Maya、Blender、Unreal、D3D 原数据等
- 统一缩放、反转法线、反转绕序、垂直翻转 UV
- 映射、解码方式、坐标系与导出选项写入本地缓存，下次打开自动恢复
- 导出过程带进度条，支持取消

## 环境要求

- RenderDoc **≥ 1.4**（`extension_api` v1，见 `extension.json`）
- FBX 导出需将 **aspose-3d** 放到扩展根目录的 `aspose/` 下（不纳入 git）

## 安装

1. 将整个 `RenderDocExporter` 目录放到 RenderDoc 扩展目录，例如：
   - Windows: `%APPDATA%\qrenderdoc\extensions\RenderDocExporter`
2. 若需 FBX 导出，自行配置 `aspose/` 依赖
3. 打开 **Tools → Extension Manager**，启用 **Renderdoc Exporter**

> 更新扩展代码后请 **完全重启 RenderDoc**（不要仅 Reload），避免热重载残留旧 Python 模块导致 `ImportError`。

## 使用方法

1. 在 **Event Browser** 或 **Mesh Preview** 中选中一条 **Draw Call**
2. 右键菜单选择 **导出为模型**
3. 在配置对话框中：
   - 为各 VS Input 选择语义映射（None / Position / Normal / …）
   - 为各 VS Input 选择解码方式（Float / UInt / Int）
   - 设置坐标系预设、统一缩放、法线 / 绕序 / UV 选项
4. 点击 **确认**，选择保存路径（`.fbx` 或 `.obj`）
5. 等待进度条完成

**说明：**

- 导出 EID 为 Event Browser 当前光标所在事件（`CurEvent()`）
- 属性列表按语义优先级排序（Position → Normal → Tangent → Color → UV → 其它）
- 无缓存时，插件会根据属性名自动猜测默认映射（如含 `position` → Position）
- 仅支持非实例化（`perInstance`）的 VS Input；当前 EID 须为有效 Draw Call 且含索引数据

## 导出设置

### 数据映射与解码

每个 VS Input 一行，包含 **语义映射** 与 **解码方式** 两个下拉框：

| 解码模式 | 行为 |
|----------|------|
| **Float**（默认） | 按 RenderDoc 顶点 `compType` 自动解码（Float、UNorm、SNorm 等） |
| **UInt** | 强制按无符号整型读取，以 HLSL `asfloat` 位模式写入 float |
| **Int** | 强制按有符号整型读取，直接导出为 float 数值 |

**示例：** UNorm8 颜色值 `155` 在 Float 模式下解码为 `155/255 ≈ 0.608`；若误用 UInt 会得到 `asfloat(155) ≈ 2.17e-43`。

### 坐标系预设

相对 D3D VS Input 常见 **左手 Y-up** 对象空间（见 `util.py` → `ExportConfig._transform_coord`）：

| 预设 id | UI 名称 | 变换 `(x, y, z) →` |
|---------|---------|-------------------|
| `opengl`（默认） | OpenGL（右手 Y-up） | `(x, y, -z)` |
| `maya` | Maya（右手 Y-up） | `(x, y, -z)` |
| `blender` | Blender（右手 Z-up） | `(x, -z, y)` |
| `unreal` | Unreal Engine（左手 Z-up） | `(x, z, y)` |
| `d3d_raw` | 原数据（D3D 左手 Y-up） | `(x, y, z)` |
| `legacy_z` | 旧版 Z 轴向上（仅缓存兼容） | `(y, -x, z)` |

- **顶点位置**：坐标系变换后乘 **统一缩放**
- **法线 / 切线**：仅坐标系变换，不缩放

### 其他选项

| 选项 | 默认 | 说明 |
|------|------|------|
| 统一缩放 | `1.0` | 范围 `0.0001` ~ `100000`，仅作用于位置 |
| 反转法线 | 开启 | 修正 D3D 与常见 OBJ 查看器手性差异 |
| 反转三角形绕序 | 开启 | 与反转法线配合修正背面剔除 |
| 垂直翻转 UV | 关闭 | 对 V 做 `1 - v` |

### 输出格式

| 格式 | 行为 |
|------|------|
| **FBX** | 单文件；多套 UV 写入不同 TextureMapping 语义 |
| **OBJ** | 每个 UV 通道单独一个 `.obj` 文件（主文件名加后缀） |

## 设置缓存

点击 **确认** 后写入扩展根目录 `export_mapping_cache.json`（运行时生成，已在 `.gitignore` 中忽略）。

```json
{
  "version": 1,
  "header_mappings": {
    "POSITION": "Position",
    "NORMAL": "Normal",
    "TEXCOORD": "UV"
  },
  "export_settings": {
    "coord_preset": "blender",
    "coord_preset_label": "Blender（右手 Z-up）",
    "up_axis": "Z",
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

| 字段 | 说明 |
|------|------|
| `header_mappings` | 属性名 → 语义（Position / Normal / …） |
| `header_decode_modes` | 属性名 → 解码模式（`float` / `uint` / `int`） |
| `coord_preset` | 坐标系预设 id |
| `coord_preset_label` | 坐标系 UI 显示名（MiniQt 下拉框恢复用） |
| `up_axis` | 兼容旧缓存（`Y` / `Z`） |

## 顶点解码

解码逻辑位于 `csv_to_model/vertex_decode.py`，解码模式常量与 `normalize_decode_mode()` 位于 `util.py`。

**Float 模式** 按 RenderDoc `compType` 选择路径：

- `Float` → 浮点解包（含 half / float / double）
- `UNorm` / `UNormSRGB` → 归一化到 `[0, 1]`
- `SNorm` → 归一化到 `[-1, 1]`
- `UInt` → `asfloat` 位模式
- `SInt` → 有符号整型转 float
- 打包格式（R10G10B10A2、R11G11B10、R5G6B5、A8 等）→ 对应语义解码

**UInt / Int 模式** 由用户在对话框中强制指定，覆盖格式语义，用于纠正特殊缓冲区的误读。

## 项目结构

```
RenderDocExporter/
├── __init__.py                  # 扩展入口：菜单注册、导出流程、进度条
├── extension.json               # 扩展元数据（name / version / minimum_renderdoc）
├── README.md
├── export_mapping_cache.json    # 用户设置缓存（运行时生成）
├── csv_to_model/
│   ├── mesh_from_eid.py         # 从 EID 读取 VS Input 网格与索引
│   ├── vertex_decode.py         # 顶点格式解码（compType + 手动覆盖）
│   ├── exporter_dialog.py       # MiniQt 配置对话框与缓存读写
│   ├── util.py                  # Vertex / ExportConfig / 坐标变换 / 解码模式
│   ├── fbx_exporter.py          # FBX 写入（Aspose.3D）
│   ├── obj_exporter.py          # OBJ 写入（多 UV 分文件）
│   └── exprorter.py             # 热重载兼容桩（转发 mesh_from_eid）
└── aspose/                      # FBX 依赖（需自行放置）
```

## 已知限制

- 不支持实例化顶点属性（`perInstance`）
- 不支持压缩/非 VS Input 数据源；须从当前 Draw Call 的 VS Input 读取
- FBX 顶点属性均为 float；大于 32 位的整型需自行拆分通道
- 扩展热重载可能加载旧版模块；更新代码后请重启 RenderDoc

## 作者

zcx \<zcxtimesup@gmail.com\>（与 `extension.json` 中 author 一致）

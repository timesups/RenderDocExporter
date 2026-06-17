import aspose.threed as a3d
import aspose.threed.entities as a3d_ent
from aspose.threed.utilities import FVector4, Vector2, Vector4

from typing import Callable, Optional, Tuple

from .obj_exporter import _vertex_uv_channel_count
from .util import *


# FBX 中多套 UV 通过不同 TextureMapping 语义区分；与 OBJ 多文件一通道对应，此处单文件多通道。
_UV_TEXTURE_MAPPINGS: Tuple[a3d_ent.TextureMapping, ...] = (
    a3d_ent.TextureMapping.DIFFUSE,
    a3d_ent.TextureMapping.BUMP,
    a3d_ent.TextureMapping.EMISSIVE,
    a3d_ent.TextureMapping.AMBIENT,
    a3d_ent.TextureMapping.SPECULAR,
    a3d_ent.TextureMapping.SHININESS,
    a3d_ent.TextureMapping.OPACITY,
    a3d_ent.TextureMapping.REFLECTION,
    a3d_ent.TextureMapping.GLOW,
    a3d_ent.TextureMapping.DISPLACEMENT,
    a3d_ent.TextureMapping.SHADOW,
)


def _pose_position(
    config: Optional[ExportConfig], x: float, y: float, z: float
) -> Tuple[float, float, float]:
    if config is None:
        return (float(x), float(y), float(z))
    return config.transform_position(x, y, z)


def _pose_direction(
    config: Optional[ExportConfig], x: float, y: float, z: float
) -> Tuple[float, float, float]:
    """法线 / 切线：坐标系变换，不含统一缩放。"""
    if config is None:
        return (float(x), float(y), float(z))
    return config.transform_direction(x, y, z)


def _vec_to_vertex_color_f4(v: Vec) -> FVector4:
    """顶点色线性空间 RGBA；分量直接来自 Vertex.Color（Vec）。"""
    return FVector4(float(v.x), float(v.y), float(v.z), float(v.w))


def write_vertices_to_fbx(
    vertices: List[Vertex],
    indices: List[int],
    filepath: str,
    *,
    flip_normals: bool = True,
    flip_winding: bool = True,
    config: Optional[ExportConfig] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> None:
    """
    将顶点列表与紧凑三角形索引写入 FBX（二进制 FBX 7.5），UTF-8 路径由调用方保证。

    - 位置、法线应用与 OBJ 相同的 ExportConfig.transform_xyz / flip_normals / flip_winding；UV 可选 transform_uv（垂直翻转 V）。
    - 所有 UV 通道一并写入（通过多套 TextureMapping 区分），对应 Vertex.uvs 中顺序。
    - 若任一顶点的 Color 非空，则为整张网格写入顶点色通道；缺省颜色为白。
    """
    if config is not None:
        flip_normals = config.flip_normals
        flip_winding = config.flip_winding
    if not vertices:
        raise ValueError("vertices 为空")
    for i in indices:
        if i < 0 or i >= len(vertices):
            raise IndexError(f"索引 {i} 超出顶点范围 0..{len(vertices) - 1}")

    n_uv = _vertex_uv_channel_count(vertices)
    if n_uv > len(_UV_TEXTURE_MAPPINGS):
        raise ValueError(
            f"UV 通道数 {n_uv} 超过当前 FBX 导出映射表长度 {len(_UV_TEXTURE_MAPPINGS)}，请扩展 _UV_TEXTURE_MAPPINGS"
        )

    tri_len = len(indices) - len(indices) % 3
    tri_count = tri_len // 3
    total_steps = max(1, len(vertices) + tri_count + 1)
    prog_stride = max(1, total_steps // 150)
    prog_step = 0

    mesh = a3d_ent.Mesh()
    mesh.name = "exported_mesh"

    for v in vertices:
        px, py, pz = _pose_position(
            config, v.Position.x, v.Position.y, v.Position.z
        )
        mesh.control_points.append(Vector4(px, py, pz, 1.0))
        prog_step += 1
        if on_progress is not None and (
            prog_step % prog_stride == 0 or prog_step == len(vertices)
        ):
            on_progress(prog_step, total_steps)

    for t in range(0, tri_len, 3):
        a = indices[t]
        b = indices[t + 1]
        c = indices[t + 2]
        if flip_winding:
            b, c = c, b
        mesh.create_polygon(a, b, c)
        prog_step += 1
        if on_progress is not None and (
            prog_step % prog_stride == 0 or prog_step == len(vertices) + tri_count
        ):
            on_progress(prog_step, total_steps)

    # 法线（CONTROL_POINT + DIRECT，与 OBJ 每顶点 vn 一致）
    vn = a3d_ent.VertexElementNormal()
    vn.mapping_mode = a3d_ent.MappingMode.CONTROL_POINT
    vn.reference_mode = a3d_ent.ReferenceMode.DIRECT
    for v in vertices:
        if v.Normal is None:
            nx, ny, nz = 0.0, 0.0, 1.0
        else:
            nx, ny, nz = (
                float(v.Normal.x),
                float(v.Normal.y),
                float(v.Normal.z),
            )
        if flip_normals:
            nx, ny, nz = -nx, -ny, -nz
        nx, ny, nz = _pose_direction(config, nx, ny, nz)
        vn.data.append(FVector4(nx, ny, nz, 0.0))
    mesh.add_element(vn)

    # 切线（CONTROL_POINT + DIRECT；w 为副切线方向符号，保留原始值）
    if any(v.Tangent is not None for v in vertices):
        vt = a3d_ent.VertexElementTangent()
        vt.mapping_mode = a3d_ent.MappingMode.CONTROL_POINT
        vt.reference_mode = a3d_ent.ReferenceMode.DIRECT
        for v in vertices:
            if v.Tangent is None:
                tx, ty, tz, tw = 1.0, 0.0, 0.0, 1.0
            else:
                tx, ty, tz = (
                    float(v.Tangent.x),
                    float(v.Tangent.y),
                    float(v.Tangent.z),
                )
                tw = float(v.Tangent.w) if v.Tangent.w else 1.0
            tx, ty, tz = _pose_direction(config, tx, ty, tz)
            vt.data.append(FVector4(tx, ty, tz, tw))
        mesh.add_element(vt)

    # 多 UV：每层对应 Vertex.uvs[ch]
    for ch in range(n_uv):
        uv_el = mesh.create_element_uv(_UV_TEXTURE_MAPPINGS[ch])
        uv_el.mapping_mode = a3d_ent.MappingMode.CONTROL_POINT
        uv_el.reference_mode = a3d_ent.ReferenceMode.DIRECT
        layer_data = []
        for v in vertices:
            if config is not None:
                tu, tv = config.transform_uv(v.uvs[ch].x, v.uvs[ch].y)
            else:
                tu, tv = float(v.uvs[ch].x), float(v.uvs[ch].y)
            layer_data.append(Vector2(tu, tv))
        uv_el.add_data(layer_data)

    # 顶点色
    if any(v.Color is not None for v in vertices):
        vc = a3d_ent.VertexElementVertexColor()
        vc.name = "Color"
        vc.mapping_mode = a3d_ent.MappingMode.CONTROL_POINT
        vc.reference_mode = a3d_ent.ReferenceMode.DIRECT
        for v in vertices:
            if v.Color is None:
                vc.data.append(FVector4(1.0, 1.0, 1.0, 1.0))
            else:
                vc.data.append(_vec_to_vertex_color_f4(v.Color))
        mesh.add_element(vc)

    scene = a3d.Scene()
    scene.root_node.create_child_node("mesh_root").add_entity(mesh)

    save_options = a3d.formats.FbxSaveOptions(a3d.FileFormat.FBX7500_BINARY)
    scene.save(filepath, save_options)

    prog_step = total_steps
    if on_progress is not None:
        on_progress(prog_step, total_steps)

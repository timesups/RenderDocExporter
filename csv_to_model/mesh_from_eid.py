"""从当前 EID 经 Replay API 解码 VS Input 网格顶点与索引。"""

import struct
from typing import Callable, Dict, List, Mapping, Optional, Tuple

import renderdoc as rd

from .util import DataColumnTypeMap, DataType, Vec, Vertex, normalize_decode_mode
from .vertex_decode import element_size, unpack_vertex_data


class _MeshAttr(rd.MeshFormat):
    indexOffset = 0


def _get_mesh_inputs(controller, draw):
    state = controller.GetPipelineState()
    ib = state.GetIBuffer()
    vbs = state.GetVBuffers()
    attrs = state.GetVertexInputs()
    mesh_inputs = []

    for attr in attrs:
        if attr is None:
            continue
        if attr.perInstance:
            continue

        vb_idx = attr.vertexBuffer
        if vb_idx < 0 or vb_idx >= len(vbs):
            continue
        vb = vbs[vb_idx]
        if vb is None or vb.resourceId == rd.ResourceId.Null():
            continue

        attr_name = attr.name
        if not attr_name:
            attr_name = "INPUT%d" % len(mesh_inputs)

        mesh_input = _MeshAttr()
        mesh_input.indexResourceId = ib.resourceId
        mesh_input.indexByteOffset = ib.byteOffset
        mesh_input.indexByteStride = ib.byteStride
        mesh_input.baseVertex = draw.baseVertex
        mesh_input.indexOffset = draw.indexOffset
        mesh_input.numIndices = draw.numIndices

        if not (draw.flags & rd.ActionFlags.Indexed):
            mesh_input.indexResourceId = rd.ResourceId.Null()

        mesh_input.vertexByteOffset = (
            attr.byteOffset
            + vb.byteOffset
            + draw.vertexOffset * vb.byteStride
        )
        mesh_input.format = attr.format
        mesh_input.vertexResourceId = vb.resourceId
        mesh_input.vertexByteStride = vb.byteStride
        mesh_input.name = attr_name
        mesh_inputs.append(mesh_input)

    return mesh_inputs


def _get_indices(controller, mesh):
    index_format = "B"
    if mesh.indexByteStride == 2:
        index_format = "H"
    elif mesh.indexByteStride == 4:
        index_format = "I"

    index_format = str(mesh.numIndices) + index_format

    if mesh.indexResourceId != rd.ResourceId.Null():
        byte_offset = mesh.indexByteOffset + mesh.indexOffset * mesh.indexByteStride
        byte_count = mesh.numIndices * mesh.indexByteStride
        ibdata = controller.GetBufferData(
            mesh.indexResourceId, byte_offset, byte_count
        )
        indices = struct.unpack_from(index_format, ibdata, 0)
        return [i + mesh.baseVertex for i in indices]

    return list(range(mesh.numIndices))


def _load_vb_caches(controller, mesh_attrs, raw_indices, data_map):
    """按索引范围按需读取顶点缓冲，避免 GetBufferData(rid, 0, 0) 全量加载。"""
    if not raw_indices:
        return {}

    min_idx = min(raw_indices)
    max_idx = max(raw_indices)
    rid_ranges = {}

    for attr in mesh_attrs:
        base = attr.name.split(".")[0]
        if base not in data_map:
            continue
        if data_map[base] == DataType.NoneType:
            continue

        rid = attr.vertexResourceId
        stride = int(attr.vertexByteStride)
        elem = element_size(attr.format)
        start = int(attr.vertexByteOffset) + min_idx * stride
        end = int(attr.vertexByteOffset) + max_idx * stride + elem
        if rid not in rid_ranges:
            rid_ranges[rid] = [start, end]
        else:
            rid_ranges[rid][0] = min(rid_ranges[rid][0], start)
            rid_ranges[rid][1] = max(rid_ranges[rid][1], end)

    vb_cache = {}
    for rid, (lo, hi) in rid_ranges.items():
        vb_cache[rid] = (controller.GetBufferData(rid, lo, hi - lo), lo)
    return vb_cache


def size_map_from_attributes(mesh_attrs):
    sizes = {}
    for attr in mesh_attrs:
        if attr is None or not attr.name:
            continue
        base = attr.name.split(".")[0]
        comp = int(attr.format.compCount)
        if base not in sizes:
            sizes[base] = comp
        else:
            sizes[base] = max(sizes[base], comp)
    return sizes


def _action_label(action):
    if action is None:
        return ""
    for attr in ("customName", "name"):
        value = getattr(action, attr, None)
        if value:
            return str(value)
    return ""


def _find_first_draw_eid(action):
    """在动作子树中查找首个 numIndices > 0 的 Draw Call EID（迭代，避免深递归）。"""
    queue = [action]
    while queue:
        node = queue.pop(0)
        if node is None:
            continue
        if int(getattr(node, "numIndices", 0) or 0) > 0:
            return int(node.eventId)
        queue.extend(getattr(node, "children", None) or [])
    return None


def _format_no_indices_error(eid, draw):
    child_eid = _find_first_draw_eid(draw)
    label = _action_label(draw)
    is_batch_marker = bool(
        int(getattr(draw, "flags", 0) or 0) & int(rd.ActionFlags.MultiAction)
    )
    if child_eid is not None and (
        is_batch_marker or "ExecuteIndirect" in label
    ):
        return (
            "EID %d 是 ExecuteIndirect 等批次标记（numIndices=0），"
            "请在 Event Browser 中选中子 Draw Call，例如 EID %d"
        ) % (eid, child_eid)
    return "EID %d 没有可导出的图元" % eid


def probe_mesh_headers(pyrenderdoc_):
    """探测当前 EID 的 VS Input 顶点属性，返回 (size_map, error_message)。"""
    result = {"size_map": {}, "error": None}

    def _probe(controller):
        eid = pyrenderdoc_.CurEvent()
        draw = pyrenderdoc_.GetAction(eid)
        if draw is None:
            result["error"] = "EID %d 不是 Draw Call" % eid
            return
        if draw.numIndices <= 0:
            result["error"] = _format_no_indices_error(eid, draw)
            return

        controller.SetFrameEvent(eid, True)
        try:
            mesh_attrs = _get_mesh_inputs(controller, draw)
        except RuntimeError as exc:
            result["error"] = str(exc)
            return

        if not mesh_attrs:
            result["error"] = "未找到 VS Input 顶点属性"
            return

        result["size_map"] = size_map_from_attributes(mesh_attrs)

    pyrenderdoc_.Replay().BlockInvoke(_probe)
    return result["size_map"], result["error"]


def get_data_from_eid(
    pyrenderdoc_,
    size_map,
    data_map,
    on_progress=None,
    decode_mode_map=None,
):
    """从当前 EID 解码 VS Input 顶点与索引。"""
    result = {"vertices": [], "indices": []}
    decode_mode_map = decode_mode_map or {}

    def _fetch(controller):
        eid = pyrenderdoc_.CurEvent()
        draw = pyrenderdoc_.GetAction(eid)
        if draw is None:
            raise RuntimeError("EID %d 不是 Draw Call" % eid)
        if draw.numIndices <= 0:
            raise RuntimeError(_format_no_indices_error(eid, draw))

        controller.SetFrameEvent(eid, True)
        mesh_attrs = _get_mesh_inputs(controller, draw)
        if not mesh_attrs:
            raise RuntimeError("未找到 VS Input 顶点属性")

        raw_indices = _get_indices(controller, mesh_attrs[0])
        vb_cache = _load_vb_caches(controller, mesh_attrs, raw_indices, data_map)

        def _read_attr(attr, idx):
            rid = attr.vertexResourceId
            data, cache_base = vb_cache[rid]
            offset = attr.vertexByteOffset + attr.vertexByteStride * idx - cache_base
            size = element_size(attr.format)
            chunk = data[offset : offset + size]
            base = attr.name.split(".")[0]
            mode = normalize_decode_mode(decode_mode_map.get(base, "float"))
            return unpack_vertex_data(attr.format, chunk, decode_mode=mode)

        vertices = []
        indices = []
        idx_to_slot = {}

        for idx in raw_indices:
            if idx not in idx_to_slot:
                vertex = Vertex()
                for attr in mesh_attrs:
                    base = attr.name.split(".")[0]
                    if base not in data_map:
                        continue
                    dtype = data_map[base]
                    if dtype == DataType.NoneType:
                        continue
                    value = _read_attr(attr, idx)
                    n = size_map.get(base, len(value))
                    vertex.fill_data(dtype, Vec(value[:n]))
                idx_to_slot[idx] = len(vertices)
                vertices.append(vertex)
            indices.append(idx_to_slot[idx])

        result["vertices"] = vertices
        result["indices"] = indices

    pyrenderdoc_.Replay().BlockInvoke(_fetch)
    return result["vertices"], result["indices"]

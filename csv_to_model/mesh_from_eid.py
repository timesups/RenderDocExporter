"""从当前 EID 经 Replay API 解码 VS Input 网格顶点与索引。"""

import struct
from typing import Callable, Dict, List, Mapping, Optional, Tuple

import renderdoc as rd

from .util import DataColumnTypeMap, DataType, Vec, Vertex
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
            raise RuntimeError("暂不支持实例化顶点属性")

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
        ibdata = controller.GetBufferData(
            mesh.indexResourceId, mesh.indexByteOffset, 0
        )
        offset = mesh.indexOffset * mesh.indexByteStride
        indices = struct.unpack_from(index_format, ibdata, offset)
        return [i + mesh.baseVertex for i in indices]

    return list(range(mesh.numIndices))


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
            result["error"] = "EID %d 没有可导出的图元" % eid
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
):
    """从当前 EID 解码 VS Input 顶点与索引。"""
    result = {"vertices": [], "indices": []}

    def _fetch(controller):
        eid = pyrenderdoc_.CurEvent()
        draw = pyrenderdoc_.GetAction(eid)
        if draw is None:
            raise RuntimeError("EID %d 不是 Draw Call" % eid)

        controller.SetFrameEvent(eid, True)
        mesh_attrs = _get_mesh_inputs(controller, draw)
        if not mesh_attrs:
            raise RuntimeError("未找到 VS Input 顶点属性")

        raw_indices = _get_indices(controller, mesh_attrs[0])
        vb_cache = {}

        def _read_attr(attr, idx):
            rid = attr.vertexResourceId
            if rid not in vb_cache:
                vb_cache[rid] = controller.GetBufferData(rid, 0, 0)
            offset = attr.vertexByteOffset + attr.vertexByteStride * idx
            size = element_size(attr.format)
            data = vb_cache[rid][offset : offset + size]
            return unpack_vertex_data(attr.format, data)

        vertices = []
        indices = []
        idx_to_slot = {}
        total = len(raw_indices)
        report_every = max(1, total // 400) if total else 1

        for i, idx in enumerate(raw_indices):
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

            if on_progress is not None and (
                i % report_every == 0 or i == total - 1
            ):
                on_progress(i + 1, total)

        result["vertices"] = vertices
        result["indices"] = indices

    pyrenderdoc_.Replay().BlockInvoke(_fetch)
    return result["vertices"], result["indices"]

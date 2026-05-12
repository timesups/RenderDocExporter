from typing import Callable, Mapping, Optional

from .obj_exporter import *


def get_size_per_data(headers) -> Dict[str, int]:
    sizes = {}
    for header in headers:
        header = header.split(".")[0]
        if header not in sizes.keys():
            sizes[header] = 1
        else:
            sizes[header] += 1
    return sizes


def get_vertex(row_datas, sizes: Mapping[str, int], data_map: DataColumnTypeMap):
    vertex_id = int(row_datas[0])
    index = int(row_datas[1])
    row_datas = [float(v) for v in row_datas[2:]]

    vertex: Vertex = Vertex()
    for key in data_map.keys():
        vertex.fill_data(data_map[key], Vec(*row_datas[0 : sizes[key]]))
        row_datas = row_datas[sizes[key] :]
    return vertex_id, index, vertex


def get_data_from_model(
    model,
    sizes: Mapping[str, int],
    data_map: DataColumnTypeMap,
    on_progress: Optional[Callable[[int, int], None]] = None,
):
    row_count = model.rowCount()
    column_count = model.columnCount()

    indices: List[int] = []
    vertices: List[Vertex] = []
    idx_to_slot: dict[int, int] = {}

    report_every = max(1, row_count // 400) if row_count else 1

    for row in range(0, row_count):
        row_data = [model.data(model.index(row, colum)) for colum in range(0, column_count)]
        _vertex_id, index, vertex = get_vertex(row_data, sizes, data_map)
        if index not in idx_to_slot:
            idx_to_slot[index] = len(vertices)
            vertices.append(vertex)
        # 每一行对应一次图元角点，必须追加重映射后的索引；不能只在「首次见到 IDX」时追加，
        # 否则 indices 长度远小于 CSV 行数，三角形会错位、破面。
        indices.append(idx_to_slot[index])
        if on_progress is not None and (
            row % report_every == 0 or row == row_count - 1
        ):
            on_progress(row + 1, row_count)
    return vertices, indices

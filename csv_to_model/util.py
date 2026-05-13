from typing import Dict, List, Tuple, overload

# 表头基名 -> DataType 整型，与 get_data_from_model(..., data_map) 一致
DataColumnTypeMap = Dict[str, int]


class ExportConfig:
    """导出选项：轴向、法线/绕序、UV 垂直翻转等，由对话框填入并传入 OBJ 等写入函数。"""

    UP_Z = "Z"
    UP_Y = "Y"

    def __init__(
        self,
        *,
        up_axis: str = "Z",
        flip_normals: bool = True,
        flip_winding: bool = True,
        flip_uv_v: bool = False,
    ) -> None:
        self.up_axis = up_axis if up_axis in (self.UP_Z, self.UP_Y) else self.UP_Z
        self.flip_normals = flip_normals
        self.flip_winding = flip_winding
        self.flip_uv_v = flip_uv_v

    def transform_uv(self, u: float, v: float) -> Tuple[float, float]:
        """垂直翻转 UV：对 V 做 1-v（常见图像坐标与渲染 UV 轴向对齐）。"""
        u, v = float(u), float(v)
        if self.flip_uv_v:
            v = 1.0 - v
        return (u, v)

    def transform_xyz(self, x: float, y: float, z: float) -> Tuple[float, float, float]:
        """选 Z 轴向上：不旋转。选 Y 轴向上：绕 Y 轴旋转 +90°（右手系，弧度 π/2）。"""
        if self.up_axis == self.UP_Y:
            return (float(x), float(y), float(z))
        return (float(y), float(-x), float(z))

class Vec:
    x: float = 0
    y: float = 0
    z: float = 0
    w: float = 0

    @overload
    def __init__(self, x: float, y: float) -> None: ...
    @overload
    def __init__(self, x: float, y: float, z: float) -> None: ...
    @overload
    def __init__(self, x: float, y: float, z: float, w: float) -> None: ...

    def __init__(self, x: float, y: float, z: float = 0.0, w: float = 0.0) -> None:
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.w = float(w)
    def __str__(self) -> str:
        return f"(x:{self.x},y:{self.y},z:{self.z},w:{self.w})"
    def __repr__(self) -> str:
        return self.__str__();

class DataType:
    NoneType = 0
    Position = 1
    Normal = 2
    Color = 3
    UV = 4

class Vertex:
    def __init__(self) -> None:
        self.Position: Vec = None
        self.Normal: Vec = None
        self.Color: Vec = None
        self.uvs: List[Vec] = []
    def fill_data(self, data_type: DataType, value: Vec) -> None:
        if data_type == DataType.Position:
            self.Position = value
        elif data_type == DataType.Normal:
            self.Normal = value
        elif data_type == DataType.Color:
            self.Color = value
        elif data_type == DataType.UV:
            self.uvs.append(value)
        else:
            pass
    def __str__(self) -> str:
        s = f"Vertex:[pos:{self.Position}],[nor:{self.Normal}][color:{self.Color}]"
        index = 0
        for uv in self.uvs:
            s += f"[uv{index}:{uv}]"
            index += 1
        return  s
    def __repr__(self) -> str:
        return self.__str__();
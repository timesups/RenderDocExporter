from typing import Dict, List, Sequence, Tuple, Union, overload

# 属性基名 -> DataType 整型，与 get_data_from_eid(..., data_map) 一致
DataColumnTypeMap = Dict[str, int]


class ExportConfig:
    """导出选项：坐标系预设、法线/绕序、UV 垂直翻转等。"""

    UP_Z = "Z"
    UP_Y = "Y"

    # 坐标系预设 id（写入缓存）
    COORD_OPENGL = "opengl"
    COORD_MAYA = "maya"
    COORD_BLENDER = "blender"
    COORD_UNREAL = "unreal"
    COORD_D3D_RAW = "d3d_raw"
    COORD_LEGACY_Z = "legacy_z"

    COORD_PRESET_OPTIONS = (
        (COORD_OPENGL, "OpenGL（右手 Y-up）"),
        (COORD_MAYA, "Maya（右手 Y-up）"),
        (COORD_BLENDER, "Blender（右手 Z-up）"),
        (COORD_UNREAL, "Unreal Engine（左手 Z-up）"),
        (COORD_D3D_RAW, "原数据（D3D 左手 Y-up）"),
    )

    _VALID_COORD_PRESETS = frozenset(
        opt[0] for opt in COORD_PRESET_OPTIONS
    ) | frozenset([COORD_LEGACY_Z])

    def __init__(
        self,
        *,
        coord_preset=None,
        up_axis=None,
        flip_normals=True,
        flip_winding=True,
        flip_uv_v=False,
        uniform_scale=1.0,
    ):
        if coord_preset is not None:
            self.coord_preset = (
                coord_preset
                if coord_preset in self._VALID_COORD_PRESETS
                else self.COORD_OPENGL
            )
        elif up_axis == self.UP_Z:
            self.coord_preset = self.COORD_LEGACY_Z
        elif up_axis == self.UP_Y:
            self.coord_preset = self.COORD_D3D_RAW
        else:
            self.coord_preset = self.COORD_OPENGL

        self.flip_normals = flip_normals
        self.flip_winding = flip_winding
        self.flip_uv_v = flip_uv_v
        try:
            scale = float(uniform_scale)
        except (TypeError, ValueError):
            scale = 1.0
        self.uniform_scale = scale if scale > 0.0 else 1.0

    @property
    def up_axis(self):
        """兼容 OBJ 注释等：Z-up 预设返回 Z，其余返回 Y。"""
        if self.coord_preset in (self.COORD_BLENDER, self.COORD_UNREAL, self.COORD_LEGACY_Z):
            return self.UP_Z
        return self.UP_Y

    @classmethod
    def label_for_preset(cls, preset_id):
        for pid, label in cls.COORD_PRESET_OPTIONS:
            if pid == preset_id:
                return label
        if preset_id == cls.COORD_LEGACY_Z:
            return "旧版 Z 轴向上"
        return cls.COORD_PRESET_OPTIONS[0][1]

    def transform_uv(self, u, v):
        """垂直翻转 UV：对 V 做 1-v（常见图像坐标与渲染 UV 轴向对齐）。"""
        u, v = float(u), float(v)
        if self.flip_uv_v:
            v = 1.0 - v
        return (u, v)

    def transform_xyz(self, x, y, z):
        """兼容旧调用：等同 transform_position。"""
        return self.transform_position(x, y, z)

    def _transform_coord(self, x, y, z):
        """
        将 D3D VS Input 常见左手 Y-up 对象空间，变换到目标坐标系（不含缩放）。
        """
        x, y, z = float(x), float(y), float(z)
        preset = self.coord_preset

        if preset == self.COORD_D3D_RAW:
            return (x, y, z)
        if preset in (self.COORD_OPENGL, self.COORD_MAYA):
            return (x, y, -z)
        if preset == self.COORD_BLENDER:
            return (x, -z, y)
        if preset == self.COORD_UNREAL:
            return (x, z, y)
        if preset == self.COORD_LEGACY_Z:
            return (y, -x, z)
        return (x, y, -z)

    def transform_position(self, x, y, z):
        """位置：坐标系变换后乘统一缩放。"""
        tx, ty, tz = self._transform_coord(x, y, z)
        s = self.uniform_scale
        return (tx * s, ty * s, tz * s)

    def transform_direction(self, x, y, z):
        """法线 / 切线：仅坐标系变换，不缩放。"""
        return self._transform_coord(x, y, z)

class Vec:
    x: float = 0
    y: float = 0
    z: float = 0
    w: float = 0

    @overload
    def __init__(self, components: Sequence[float]) -> None: ...
    @overload
    def __init__(self, other: "Vec") -> None: ...
    @overload
    def __init__(self, x: float) -> None: ...
    @overload
    def __init__(self, x: float, y: float) -> None: ...
    @overload
    def __init__(self, x: float, y: float, z: float) -> None: ...
    @overload
    def __init__(self, x: float, y: float, z: float, w: float) -> None: ...

    def __init__(self, *args: Union[float, Sequence[float], "Vec"]) -> None:
        if len(args) == 0:
            self.x = self.y = self.z = self.w = 0.0
        elif len(args) == 1:
            one = args[0]
            if isinstance(one, Vec):
                self.x = one.x
                self.y = one.y
                self.z = one.z
                self.w = one.w
            elif isinstance(one, (list, tuple)):
                parts = one
                self.x = float(parts[0]) if len(parts) > 0 else 0.0
                self.y = float(parts[1]) if len(parts) > 1 else 0.0
                self.z = float(parts[2]) if len(parts) > 2 else 0.0
                self.w = float(parts[3]) if len(parts) > 3 else 0.0
            else:
                self.x = float(one)
                self.y = self.z = self.w = 0.0
        elif len(args) == 2:
            self.x, self.y = float(args[0]), float(args[1])
            self.z = self.w = 0.0
        elif len(args) == 3:
            self.x, self.y, self.z = float(args[0]), float(args[1]), float(args[2])
            self.w = 0.0
        else:
            self.x, self.y, self.z, self.w = (
                float(args[0]),
                float(args[1]),
                float(args[2]),
                float(args[3]),
            )
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
    Tangent = 5

class Vertex:
    def __init__(self) -> None:
        self.Position: Vec = None
        self.Normal: Vec = None
        self.Tangent: Vec = None
        self.Color: Vec = None
        self.uvs: List[Vec] = []
    def fill_data(self, data_type: DataType, value: Vec) -> None:
        if data_type == DataType.Position:
            self.Position = value
        elif data_type == DataType.Normal:
            self.Normal = value
        elif data_type == DataType.Tangent:
            self.Tangent = value
        elif data_type == DataType.Color:
            self.Color = value
        elif data_type == DataType.UV:
            self.uvs.append(value)
        else:
            pass
    def __str__(self) -> str:
        s = f"Vertex:[pos:{self.Position}],[nor:{self.Normal}][tan:{self.Tangent}][color:{self.Color}]"
        index = 0
        for uv in self.uvs:
            s += f"[uv{index}:{uv}]"
            index += 1
        return  s
    def __repr__(self) -> str:
        return self.__str__();
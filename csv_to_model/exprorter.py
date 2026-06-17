"""已弃用：保留此模块供 RenderDoc 扩展热重载兼容，逻辑见 mesh_from_eid。"""

from .mesh_from_eid import get_data_from_eid, probe_mesh_headers, size_map_from_attributes

__all__ = ["get_data_from_eid", "probe_mesh_headers", "size_map_from_attributes"]

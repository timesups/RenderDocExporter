'''
FBX 导出选项设置窗
'''

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

current_folder = Path(__file__).absolute().parent
father_folder = str(current_folder.parent)
sys.path.append(father_folder)

from .util import DataColumnTypeMap, DataType, ExportConfig

_CACHE_PATH = current_folder.parent / "export_mapping_cache.json"
_CACHE_VERSION = 1


def _data_type_from_option_label(label: str) -> int:
    """将下拉框文案转为 util.DataType 的整型常量。"""
    if label == "None":
        return int(DataType.NoneType)
    return int(getattr(DataType, label, 0))


def _header_semantic_rank(header: str) -> int:
    """顶点属性语义优先级：Position < Normal < Tangent < Color < UV < 其它。"""
    low = header.lower()
    if "position" in low or low.startswith("pos") or ".pos" in low:
        return 0
    if "normal" in low or low.startswith("nor") or ".nor" in low:
        return 1
    if "tangent" in low or low.startswith("tan") or ".tan" in low:
        return 2
    if "color" in low or low.startswith("col") or ".col" in low:
        return 3
    if "uv" in low or "texcoord" in low or "tex" in low:
        return 4
    return 5


def _sort_attribute_headers(headers: List[str]) -> List[str]:
    """按语义优先级排序，同优先级内按名称稳定排序。"""
    return sorted(headers, key=lambda h: (_header_semantic_rank(h), str(h).lower()))


def _load_mapping_cache() -> Dict[str, Any]:
    """读取上次确认的映射与导出设置；文件不存在或损坏时返回空结构。"""
    empty: Dict[str, Any] = {"header_mappings": {}, "export_settings": {}}
    try:
        if not _CACHE_PATH.is_file():
            return empty
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return empty
        header_mappings = data.get("header_mappings", {})
        export_settings = data.get("export_settings", {})
        if not isinstance(header_mappings, dict):
            header_mappings = {}
        if not isinstance(export_settings, dict):
            export_settings = {}
        return {
            "header_mappings": {
                str(k): str(v) for k, v in header_mappings.items()
            },
            "export_settings": export_settings,
        }
    except Exception:
        return empty


def _save_mapping_cache(
    header_mappings: Dict[str, str], export_settings: Dict[str, Any]
) -> None:
    """保存用户确认后的映射与导出设置。"""
    payload = {
        "version": _CACHE_VERSION,
        "header_mappings": header_mappings,
        "export_settings": export_settings,
    }
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class ModelExportDialog:
    emgr = None
    mqt = None
    data_types = ["None", "Position", "Normal", "Tangent", "Color", "UV"]
    coord_preset_ids = [pid for pid, _ in ExportConfig.COORD_PRESET_OPTIONS]
    default_coord_preset = ExportConfig.COORD_OPENGL
    default_uniform_scale = 1.0
    # 与历史 OBJ 导出默认一致：从 D3D VS Input 导出时通常需要法线取反 + 交换绕序
    default_flip_normals = True
    default_flip_winding = True

    def __init__(self, emgr_, data_headers):
        self.emgr = emgr_
        self.mqt = emgr_.GetMiniQtHelper()
        self.data_headers = _sort_attribute_headers(data_headers)
        self._header_to_option = {}
        self.header_combos = []
        cache = _load_mapping_cache()
        self._cached_header_mappings = cache["header_mappings"]
        self._cached_export_settings = cache["export_settings"]
        self._coord_preset = self._load_cached_coord_preset()
        self._coord_preset_label = self._load_cached_coord_preset_label()
        self._uniform_scale = self._cached_float(
            "uniform_scale", self.default_uniform_scale
        )
        self._chk_flip_normals = None
        self._chk_flip_winding = None
        self._coord_preset_combo = None
        self._coord_preset_desc_label = None

    def _preset_id_from_label(self, label):
        for pid, opt_label in ExportConfig.COORD_PRESET_OPTIONS:
            if label == opt_label:
                return pid
        if isinstance(label, str):
            low = label.lower()
            if "opengl" in low:
                return ExportConfig.COORD_OPENGL
            if "maya" in low:
                return ExportConfig.COORD_MAYA
            if "blender" in low:
                return ExportConfig.COORD_BLENDER
            if "unreal" in low or "ue" in low:
                return ExportConfig.COORD_UNREAL
            if "d3d" in low or "原数据" in label:
                return ExportConfig.COORD_D3D_RAW
        return self.default_coord_preset

    def _preset_id_from_combo_text(self, text):
        preset_id = str(text).strip()
        if preset_id in ExportConfig._VALID_COORD_PRESETS:
            return preset_id
        return self._preset_id_from_label(preset_id)

    def _apply_coord_preset(self, preset_id, update_desc=True):
        if preset_id not in ExportConfig._VALID_COORD_PRESETS:
            preset_id = self.default_coord_preset
        self._coord_preset = preset_id
        self._coord_preset_label = ExportConfig.label_for_preset(preset_id)
        if update_desc and self._coord_preset_desc_label is not None:
            self.mqt.SetWidgetText(
                self._coord_preset_desc_label, self._coord_preset_label
            )

    def _load_cached_coord_preset(self):
        cached = self._cached_export_settings.get("coord_preset")
        if isinstance(cached, str) and cached in ExportConfig._VALID_COORD_PRESETS:
            return cached
        cached_label = self._cached_export_settings.get("coord_preset_label")
        if isinstance(cached_label, str):
            pid = self._preset_id_from_label(cached_label)
            if pid in ExportConfig._VALID_COORD_PRESETS:
                return pid
        cached_axis = self._cached_export_settings.get("up_axis")
        if cached_axis == ExportConfig.UP_Z:
            return ExportConfig.COORD_LEGACY_Z
        if cached_axis == ExportConfig.UP_Y:
            return ExportConfig.COORD_D3D_RAW
        return self.default_coord_preset

    def _load_cached_coord_preset_label(self):
        cached_label = self._cached_export_settings.get("coord_preset_label")
        if isinstance(cached_label, str):
            for _, label in ExportConfig.COORD_PRESET_OPTIONS:
                if cached_label == label:
                    return label
        return ExportConfig.label_for_preset(self._coord_preset)

    def _on_coord_preset_changed(self, text):
        self._apply_coord_preset(self._preset_id_from_combo_text(text))

    def _guess_default_option(self, header: str) -> str:
        rank = _header_semantic_rank(header)
        if rank == 0:
            return "Position"
        if rank == 1:
            return "Normal"
        if rank == 2:
            return "Tangent"
        if rank == 3:
            return "Color"
        if rank == 4:
            return "UV"
        return "None"

    def _resolve_default_option(self, header: str) -> str:
        cached = self._cached_header_mappings.get(header)
        if cached in self.data_types:
            return cached
        return self._guess_default_option(header)

    def _cached_bool(self, key, default):
        value = self._cached_export_settings.get(key, default)
        return bool(value)

    def _cached_float(self, key, default):
        value = self._cached_export_settings.get(key, default)
        try:
            f = float(value)
            if f > 0.0:
                return f
        except (TypeError, ValueError):
            pass
        return float(default)

    def _store_header_option(self, header: str, option_text: str) -> None:
        self._header_to_option[header] = option_text

    def get_data_map(self, sizes: Optional[Dict[str, int]] = None) -> DataColumnTypeMap:
        """
        供 get_data_from_eid 的 data_map 参数。

        - key：与 size_map（probe_mesh_headers 结果）相同的属性基名；
        - value：DataType 整型（与 Vertex.fill_data 中比较一致）；
        - 键顺序与 sizes 一致（须传入 sizes，与第二参数为同一 dict 引用或相同 key 顺序）。
        """
        keys = list(sizes.keys()) if sizes is not None else list(self.data_headers)
        return {
            k: _data_type_from_option_label(self._header_to_option.get(k, "None"))
            for k in keys
        }

    def _sync_coord_preset_from_ui(self):
        """从 MiniQt 下拉框读取预设 id（ASCII）；读不到或与当前不一致时不误覆盖。"""
        combo = self._coord_preset_combo
        if combo is None:
            return
        try:
            text = str(self.mqt.GetWidgetText(combo)).strip()
            if text in self.coord_preset_ids:
                self._apply_coord_preset(text, update_desc=True)
        except Exception:
            pass

    def _sync_uniform_scale_from_ui(self):
        w = getattr(self, "_uniform_scale_spin", None)
        if w is None:
            return
        try:
            val = float(self.mqt.GetSpinboxValue(w))
            self._uniform_scale = val if val > 0.0 else self.default_uniform_scale
        except Exception:
            pass

    def _build_export_settings_dict(self):
        return {
            "coord_preset": self._coord_preset,
            "coord_preset_label": self._coord_preset_label,
            "up_axis": ExportConfig(coord_preset=self._coord_preset).up_axis,
            "uniform_scale": float(self._uniform_scale),
            "flip_normals": bool(
                self.mqt.IsWidgetChecked(self._chk_flip_normals)
            )
            if self._chk_flip_normals is not None
            else self.default_flip_normals,
            "flip_winding": bool(
                self.mqt.IsWidgetChecked(self._chk_flip_winding)
            )
            if self._chk_flip_winding is not None
            else self.default_flip_winding,
            "flip_uv_v": bool(self.mqt.IsWidgetChecked(self._chk_flip_u))
            if getattr(self, "_chk_flip_u", None) is not None
            else False,
        }

    def get_export_config(self) -> ExportConfig:
        self._sync_coord_preset_from_ui()
        self._sync_uniform_scale_from_ui()
        settings = self._build_export_settings_dict()
        return ExportConfig(
            coord_preset=settings["coord_preset"],
            flip_normals=settings["flip_normals"],
            flip_winding=settings["flip_winding"],
            flip_uv_v=settings["flip_uv_v"],
            uniform_scale=settings["uniform_scale"],
        )

    def init_ui(self):
        self.widget = self.mqt.CreateToplevelWidget("模型导出配置", None)

        map_title = self.mqt.CreateLabel()
        self.mqt.SetWidgetText(map_title, "数据映射")
        self.mqt.AddWidget(self.widget, map_title)

        data_map_container = self.mqt.CreateVerticalContainer()
        self.mqt.AddWidget(self.widget, data_map_container)

        self.header_combos = []
        for header in self.data_headers:
            row = self.mqt.CreateHorizontalContainer()

            label = self.mqt.CreateLabel()
            self.mqt.SetWidgetText(label, str(header))
            self.mqt.AddWidget(row, label)

            combo = self.mqt.CreateComboBox(
                False,
                lambda ctx, w, text, h=header: self._store_header_option(h, str(text)),
            )
            self.mqt.SetComboOptions(combo, self.data_types)
            default_opt = self._resolve_default_option(str(header))
            self.mqt.SelectComboOption(combo, default_opt)
            self._store_header_option(header, default_opt)

            self.mqt.AddWidget(row, combo)
            self.mqt.AddWidget(data_map_container, row)
            self.header_combos.append((header, combo))

        export_title = self.mqt.CreateLabel()
        self.mqt.SetWidgetText(export_title, "导出设置")
        self.mqt.AddWidget(self.widget, export_title)

        export_settings_row = self.mqt.CreateHorizontalContainer()
        coord_label = self.mqt.CreateLabel()
        self.mqt.SetWidgetText(coord_label, "坐标系预设")
        self.mqt.AddWidget(export_settings_row, coord_label)
        coord_combo = self.mqt.CreateComboBox(
            False,
            lambda ctx, w, text: self._on_coord_preset_changed(str(text)),
        )
        self.mqt.SetComboOptions(coord_combo, self.coord_preset_ids)
        self._coord_preset_combo = coord_combo
        combo_id = (
            self._coord_preset
            if self._coord_preset in self.coord_preset_ids
            else self.default_coord_preset
        )
        self.mqt.SelectComboOption(coord_combo, combo_id)
        self.mqt.AddWidget(export_settings_row, coord_combo)
        coord_desc = self.mqt.CreateLabel()
        self._coord_preset_desc_label = coord_desc
        self.mqt.SetWidgetText(coord_desc, self._coord_preset_label)
        self.mqt.AddWidget(export_settings_row, coord_desc)
        self._apply_coord_preset(self._coord_preset, update_desc=True)
        self.mqt.AddWidget(self.widget, export_settings_row)

        scale_row = self.mqt.CreateHorizontalContainer()
        scale_label = self.mqt.CreateLabel()
        self.mqt.SetWidgetText(scale_label, "统一缩放")
        self.mqt.AddWidget(scale_row, scale_label)
        scale_spin = self.mqt.CreateSpinbox(4, 0.1)
        self.mqt.SetSpinboxBounds(scale_spin, 0.0001, 100000.0)
        self.mqt.SetSpinboxValue(scale_spin, self._uniform_scale)
        self._uniform_scale_spin = scale_spin
        self.mqt.AddWidget(scale_row, scale_spin)
        self.mqt.AddWidget(self.widget, scale_row)

        export_flags = self.mqt.CreateVerticalContainer()
        
        chk_n = self.mqt.CreateCheckbox(None)
        self.mqt.SetWidgetText(chk_n, "反转法线（推荐开启：对齐常见 D3D / 网格数据与 OBJ 查看器）")
        self.mqt.SetWidgetChecked(
            chk_n,
            self._cached_bool("flip_normals", self.default_flip_normals),
        )
        self._chk_flip_normals = chk_n
        self.mqt.AddWidget(export_flags, chk_n)

        chk_w = self.mqt.CreateCheckbox(None)
        self.mqt.SetWidgetText(chk_w, "反转三角形绕序（推荐开启：与反转法线配合修正背面剔除）")
        self.mqt.SetWidgetChecked(
            chk_w,
            self._cached_bool("flip_winding", self.default_flip_winding),
        )
        self._chk_flip_winding = chk_w
        self.mqt.AddWidget(export_flags, chk_w)

        chk_flip_u = self.mqt.CreateCheckbox(None)
        self.mqt.SetWidgetText(chk_flip_u,"垂直翻转UV")
        self.mqt.SetWidgetChecked(chk_flip_u, self._cached_bool("flip_uv_v", False))
        self._chk_flip_u = chk_flip_u
        self.mqt.AddWidget(export_flags,chk_flip_u)


        self.mqt.AddWidget(self.widget, export_flags)

        button_container = self.mqt.CreateHorizontalContainer()

        callback = lambda *args: self.mqt.CloseCurrentDialog(False)
        cancel_button = self.mqt.CreateButton(callback)
        self.mqt.SetWidgetText(cancel_button, "取消")

        ok_button = self.mqt.CreateButton(self.button_accept)
        self.mqt.SetWidgetText(ok_button, "确认")

        self.mqt.AddWidget(button_container, cancel_button)
        self.mqt.AddWidget(button_container, ok_button)
        self.mqt.AddWidget(self.widget, button_container)

        return self.widget

    def button_accept(self, context_, widget_, text_):
        self._sync_coord_preset_from_ui()
        self._sync_uniform_scale_from_ui()
        _save_mapping_cache(
            dict(self._header_to_option),
            self._build_export_settings_dict(),
        )
        self.mqt.CloseCurrentDialog(True)

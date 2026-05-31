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
    up_axis_labels = ["Z轴向上", "Y轴向上"]
    # 与历史 OBJ 导出默认一致：从 D3D/网格预览表导出时通常需要法线取反 + 交换绕序
    default_flip_normals = True
    default_flip_winding = True

    def __init__(self, emgr_, data_headers):
        self.emgr = emgr_
        self.mqt = emgr_.GetMiniQtHelper()
        self.data_headers: List[str] = _sort_attribute_headers(data_headers)
        self._header_to_option: Dict[str, str] = {}
        self.header_combos: List[Tuple[str, object]] = []
        cache = _load_mapping_cache()
        self._cached_header_mappings: Dict[str, str] = cache["header_mappings"]
        self._cached_export_settings: Dict[str, Any] = cache["export_settings"]
        self._up_axis_label: str = self._cached_export_settings.get(
            "up_axis_label", self.up_axis_labels[0]
        )
        if self._up_axis_label not in self.up_axis_labels:
            self._up_axis_label = self.up_axis_labels[0]
        self._chk_flip_normals = None
        self._chk_flip_winding = None

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

    def _cached_bool(self, key: str, default: bool) -> bool:
        value = self._cached_export_settings.get(key, default)
        return bool(value)

    def _store_header_option(self, header: str, option_text: str) -> None:
        self._header_to_option[header] = option_text

    def get_data_map(self, sizes: Optional[Dict[str, int]] = None) -> DataColumnTypeMap:
        """
        供 get_data_from_model(model, sizes, data_map) 的第三个参数。

        - key：与 sizes（get_size_per_data 结果）相同的表头基名；
        - value：DataType 整型（与 Vertex.fill_data 中比较一致）；
        - 键顺序与 sizes 一致（须传入 sizes，与第二参数为同一 dict 引用或相同 key 顺序）。
        """
        keys = list(sizes.keys()) if sizes is not None else list(self.data_headers)
        return {
            k: _data_type_from_option_label(self._header_to_option.get(k, "None"))
            for k in keys
        }

    def _sync_up_axis_from_ui(self) -> None:
        """从下拉框读取当前项（确认时调用）；避免 QString 与 str 比较失败导致轴向不生效。"""
        w = getattr(self, "_up_axis_combo", None)
        if w is None:
            return
        try:
            if hasattr(w, "currentText"):
                self._up_axis_label = str(w.currentText())
        except Exception:
            pass

    def get_export_config(self) -> ExportConfig:
        lab = str(self._up_axis_label or "").strip()
        up = ExportConfig.UP_Y if "Y轴向上" in lab else ExportConfig.UP_Z
        flip_n = self.default_flip_normals
        flip_w = self.default_flip_winding
        if self._chk_flip_normals is not None:
            flip_n = bool(self.mqt.IsWidgetChecked(self._chk_flip_normals))
        if self._chk_flip_winding is not None:
            flip_w = bool(self.mqt.IsWidgetChecked(self._chk_flip_winding))
        flip_v = False
        if getattr(self, "_chk_flip_u", None) is not None:
            flip_v = bool(self.mqt.IsWidgetChecked(self._chk_flip_u))
        return ExportConfig(
            up_axis=up,
            flip_normals=flip_n,
            flip_winding=flip_w,
            flip_uv_v=flip_v,
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
        up_label = self.mqt.CreateLabel()
        self.mqt.SetWidgetText(up_label, "坐标向上轴")
        self.mqt.AddWidget(export_settings_row, up_label)
        up_combo = self.mqt.CreateComboBox(
            False,
            lambda ctx, w, text: setattr(self, "_up_axis_label", str(text)),
        )
        self.mqt.SetComboOptions(up_combo, self.up_axis_labels)
        self.mqt.SelectComboOption(up_combo, self._up_axis_label)
        self._up_axis_combo = up_combo
        self._up_axis_label = str(self._up_axis_label)
        self.mqt.AddWidget(export_settings_row, up_combo)
        self.mqt.AddWidget(self.widget, export_settings_row)

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
        self._sync_up_axis_from_ui()
        _save_mapping_cache(
            dict(self._header_to_option),
            {
                "up_axis_label": self._up_axis_label,
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
            },
        )
        self.mqt.CloseCurrentDialog(True)

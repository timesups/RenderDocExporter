"""导出当前 EID 着色器输入绑定的贴图。"""

import os
from pathlib import Path
from typing import List, Optional, Tuple

import renderdoc as rd


def _bindings_module():
    """延迟导入，避免 RenderDoc 热重载时 bindings_util 与 texture_exporter 不同步。"""
    from . import bindings_util

    return bindings_util


def _unique_output_path(output_dir: str, stem: str) -> str:
    path = os.path.join(output_dir, stem + ".png")
    if not os.path.exists(path):
        return path
    suffix = 2
    while True:
        candidate = os.path.join(output_dir, "%s_%d.png" % (stem, suffix))
        if not os.path.exists(candidate):
            return candidate
        suffix += 1


def _save_texture_png(controller, bound, output_dir: str, safe_texture_stem) -> str:
    stem = safe_texture_stem(bound.bind_name, bound.stage, bound.resource_id)
    path = _unique_output_path(output_dir, stem)

    texsave = rd.TextureSave()
    texsave.resourceId = bound.resource_id
    texsave.destType = rd.FileType.PNG
    texsave.alpha = rd.AlphaMapping.Preserve
    texsave.mip = 0
    texsave.slice.sliceIndex = 0
    controller.SaveTexture(texsave, path)
    return path


def export_textures_for_eid(
    pyrenderdoc_,
    output_dir: str,
    *,
    eid: Optional[int] = None,
) -> Tuple[List[str], List[str]]:
    """
    导出指定 EID 各着色器阶段绑定的只读贴图到 output_dir（PNG）。
    返回 (成功路径列表, 错误/诊断信息列表)。
    """
    bu = _bindings_module()

    result = {"files": [], "errors": []}
    target_eid = int(eid if eid is not None else pyrenderdoc_.CurEvent())
    try:
        ui_bindings = bu.collect_bound_textures_from_ui(pyrenderdoc_)
    except Exception as exc:
        ui_bindings = []
        result["errors"].append("UI 贴图探测失败（将继续尝试回放线程）: %s" % exc)

    def _export(controller):
        draw = bu.find_draw_action(controller, pyrenderdoc_, target_eid)
        if draw is None:
            result["errors"].append("EID %d 不是有效事件" % target_eid)
            return
        if draw.numIndices <= 0:
            result["errors"].append("EID %d 没有可导出的 Draw Call" % target_eid)
            return

        textures, prev_draw_eid, _binding_eid = bu.collect_bound_textures_for_eid(
            controller, pyrenderdoc_, target_eid, ui_bindings=ui_bindings
        )
        if not textures:
            prev_hint = (
                "上次 Draw EID %d 至本次 Draw EID %d 之间"
                % (prev_draw_eid, target_eid)
                if prev_draw_eid
                else "Draw 前 %d 个 EID 内" % target_eid
            )
            result["errors"].append(
                "EID %d 未解析到当前 shader 使用的贴图（已在 %s 扫描绑定事件）"
                % (target_eid, prev_hint)
            )
            return

        if prev_draw_eid is not None:
            result["errors"].append(
                "贴图绑定回溯区间：上次 Draw EID %d → 本次 Draw EID %d（仅补全 Draw 上缺失的槽位）"
                % (prev_draw_eid, target_eid)
            )

        os.makedirs(output_dir, exist_ok=True)
        controller.SetFrameEvent(target_eid, True)
        for bound in textures:
            try:
                result["files"].append(
                    _save_texture_png(
                        controller, bound, output_dir, bu.safe_texture_stem
                    )
                )
            except Exception as exc:
                label = bound.bind_name or str(int(bound.resource_id))
                result["errors"].append("%s: %s" % (label, exc))

    pyrenderdoc_.Replay().BlockInvoke(_export)
    return result["files"], result["errors"]


def texture_output_dir_for_model(model_path: str) -> str:
    model = Path(model_path)
    return str(model.parent / (model.stem + "_textures"))

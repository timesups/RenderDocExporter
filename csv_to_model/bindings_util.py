"""收集 Draw Call 关联的着色器输入贴图。

收集策略沿用曾成功导出的宽口径三路合并；最后按当前 Draw shader 的贴图槽过滤，避免导出过多。
"""

import re
from typing import Callable, Dict, List, NamedTuple, Optional, Set, Tuple

import renderdoc as rd


class BoundTexture(NamedTuple):
    resource_id: rd.ResourceId
    bind_name: str
    stage: str


_SHADER_STAGES = (
    rd.ShaderStage.Vertex,
    rd.ShaderStage.Hull,
    rd.ShaderStage.Domain,
    rd.ShaderStage.Geometry,
    rd.ShaderStage.Pixel,
    rd.ShaderStage.Compute,
)

_STAGE_SHORT = {
    rd.ShaderStage.Vertex: "vs",
    rd.ShaderStage.Hull: "hs",
    rd.ShaderStage.Domain: "ds",
    rd.ShaderStage.Geometry: "gs",
    rd.ShaderStage.Pixel: "ps",
    rd.ShaderStage.Compute: "cs",
}

_BIND_LOOKBACK = 64


def _stage_label(stage) -> str:
    return _STAGE_SHORT.get(stage, "unknown")


def _access_dtype(access):
    dtype = getattr(access, "type", None)
    if dtype is None:
        dtype = getattr(access, "descriptorType", None)
    return dtype


def _default_resource_label(rid) -> str:
    return "ResourceId_%s" % int(rid)


def _texture_names_from_controller(controller) -> dict:
    names = {}
    for tex in controller.GetTextures():
        rid = tex.resourceId
        if rid == rd.ResourceId.Null():
            continue
        names[rid] = _resource_name_from_controller(controller, rid)
    return names


def _resource_name_from_controller(controller, rid) -> str:
    try:
        for res in controller.GetResources():
            if res.resourceId == rid:
                name = getattr(res, "name", None)
                if name:
                    return str(name)
                break
    except Exception:
        pass
    return _default_resource_label(rid)


def _texture_names_from_ui(pyrenderdoc_) -> dict:
    names = {}
    try:
        textures = pyrenderdoc_.GetTextures()
    except Exception:
        return names
    for tex in textures or []:
        rid = tex.resourceId
        if rid == rd.ResourceId.Null():
            continue
        try:
            name = pyrenderdoc_.GetResourceName(rid)
        except Exception:
            name = getattr(tex, "name", None)
        names[rid] = str(name) if name else _default_resource_label(rid)
    return names


def _is_texture_resource(controller, rid: rd.ResourceId, texture_names: dict) -> bool:
    if rid == rd.ResourceId.Null():
        return False
    if rid in texture_names:
        return True
    if controller is None:
        return True
    try:
        return controller.GetResourceDesc(rid).type == rd.ResourceType.Texture
    except Exception:
        return True


def _is_readonly_texture_access(access) -> bool:
    dtype = _access_dtype(access)
    if dtype is None:
        return False
    try:
        if rd.IsConstantBlockDescriptor(dtype):
            return False
        if rd.IsSamplerDescriptor(dtype) and dtype != rd.DescriptorType.ImageSampler:
            return False
        return rd.IsReadOnlyDescriptor(dtype)
    except Exception:
        return dtype in (
            rd.DescriptorType.Image,
            rd.DescriptorType.ImageSampler,
        )


def _is_texture_used_descriptor(used) -> bool:
    desc = used.descriptor
    dtype = getattr(desc, "type", None)
    if dtype is None:
        return True
    try:
        if rd.IsConstantBlockDescriptor(dtype):
            return False
        if rd.IsSamplerDescriptor(dtype) and dtype != rd.DescriptorType.ImageSampler:
            return False
        return rd.IsReadOnlyDescriptor(dtype)
    except Exception:
        return dtype in (
            rd.DescriptorType.Image,
            rd.DescriptorType.ImageSampler,
        )


def _shader_refl_name(refl, idx: int) -> str:
    if refl is None or idx < 0:
        return ""
    resources = getattr(refl, "readOnlyResources", None) or []
    if 0 <= idx < len(resources):
        res = resources[idx]
        if getattr(res, "isTexture", True):
            name = str(getattr(res, "name", "") or "")
            if name:
                return name
    for res in resources:
        if not getattr(res, "isTexture", True):
            continue
        if int(getattr(res, "fixedBindNumber", -1)) == idx:
            return str(getattr(res, "name", "") or "")
        if int(getattr(res, "bindPoint", -1)) == idx:
            return str(getattr(res, "name", "") or "")
    return ""


def _binding_name_from_reflection(get_shader, state, stage, idx: int) -> str:
    if idx < 0:
        return ""
    shader_id = state.GetShader(stage)
    if shader_id == rd.ResourceId.Null():
        return ""
    try:
        refl = get_shader(shader_id)
    except Exception:
        return ""
    return _shader_refl_name(refl, idx)


def _binding_name_from_access(get_shader, state, access) -> str:
    try:
        idx = int(access.index)
    except Exception:
        return ""
    return _binding_name_from_reflection(get_shader, state, access.stage, idx)


def _fallback_bind_name(texture_names: dict, rid: rd.ResourceId) -> str:
    return texture_names.get(rid, _default_resource_label(rid))


def _descriptor_range_from_access(access) -> rd.DescriptorRange:
    dr = rd.DescriptorRange()
    dr.offset = int(access.byteOffset)
    dr.descriptorSize = int(access.byteSize)
    dr.count = 1
    dtype = _access_dtype(access)
    if dtype is not None:
        dr.type = dtype
    return dr


def _get_readonly_resources(state, stage):
    try:
        return state.GetReadOnlyResources(stage, onlyUsed=False)
    except TypeError:
        return state.GetReadOnlyResources(stage)


def _get_all_used_descriptors(state):
    try:
        return state.GetAllUsedDescriptors(onlyUsed=False)
    except TypeError:
        try:
            return state.GetAllUsedDescriptors()
        except Exception:
            return []


def _collect_from_readonly_resources(
    state,
    texture_names: dict,
    controller,
    get_shader: Callable,
) -> List[BoundTexture]:
    out: List[BoundTexture] = []

    for stage in _SHADER_STAGES:
        if state.GetShader(stage) == rd.ResourceId.Null():
            continue

        for used in _get_readonly_resources(state, stage) or []:
            if not _is_texture_used_descriptor(used):
                continue

            rid = used.descriptor.resource
            if not _is_texture_resource(controller, rid, texture_names):
                continue

            try:
                idx = int(used.access.index)
            except Exception:
                idx = -1

            bind_name = _binding_name_from_reflection(get_shader, state, stage, idx)
            if not bind_name:
                bind_name = _fallback_bind_name(texture_names, rid)

            out.append(
                BoundTexture(
                    resource_id=rid,
                    bind_name=bind_name,
                    stage=_stage_label(stage),
                )
            )

    return out


def _collect_from_all_used_descriptors(
    state,
    texture_names: dict,
    controller,
    get_shader: Callable,
) -> List[BoundTexture]:
    out: List[BoundTexture] = []

    for used in _get_all_used_descriptors(state) or []:
        if not _is_texture_used_descriptor(used):
            continue

        rid = used.descriptor.resource
        if not _is_texture_resource(controller, rid, texture_names):
            continue

        try:
            idx = int(used.access.index)
            stage = used.access.stage
        except Exception:
            idx = -1
            stage = None
        if stage is None:
            continue

        bind_name = _binding_name_from_reflection(get_shader, state, stage, idx)
        if not bind_name:
            bind_name = _fallback_bind_name(texture_names, rid)

        out.append(
            BoundTexture(
                resource_id=rid,
                bind_name=bind_name,
                stage=_stage_label(stage),
            )
        )

    return out


def _collect_from_descriptor_access(
    controller,
    texture_names: dict,
    get_shader: Callable,
) -> List[BoundTexture]:
    out: List[BoundTexture] = []
    try:
        accesses = controller.GetDescriptorAccess()
    except Exception:
        return out

    state = controller.GetPipelineState()

    for access in accesses or []:
        if getattr(access, "staticallyUnused", False):
            continue
        if not _is_readonly_texture_access(access):
            continue

        store = access.descriptorStore
        if store == rd.ResourceId.Null():
            continue

        try:
            descs = controller.GetDescriptors(
                store, [_descriptor_range_from_access(access)]
            )
        except Exception:
            continue
        if not descs:
            continue

        rid = descs[0].resource
        if not _is_texture_resource(controller, rid, texture_names):
            continue

        bind_name = _binding_name_from_access(get_shader, state, access)
        if not bind_name:
            bind_name = _fallback_bind_name(texture_names, rid)

        out.append(
            BoundTexture(
                resource_id=rid,
                bind_name=bind_name,
                stage=_stage_label(access.stage),
            )
        )

    return out


def _collect_broad_at_eid(
    controller,
    eid: int,
    texture_names: dict,
    get_shader: Callable,
) -> List[BoundTexture]:
    """在单个 EID 用曾成功验证的三路宽口径收集。"""
    controller.SetFrameEvent(eid, True)
    state = controller.GetPipelineState()

    merged: Dict[rd.ResourceId, BoundTexture] = {}
    _merge_bound(
        merged,
        _collect_from_descriptor_access(controller, texture_names, get_shader),
    )
    _merge_bound(
        merged,
        _collect_from_readonly_resources(state, texture_names, controller, get_shader),
    )
    _merge_bound(
        merged,
        _collect_from_all_used_descriptors(
            state, texture_names, controller, get_shader
        ),
    )
    return list(merged.values())


def _merge_bound_by_slot(
    merged: Dict[Tuple[str, str], BoundTexture], found: List[BoundTexture]
) -> None:
    for bound in found:
        merged[(bound.stage, bound.bind_name)] = bound


def _merge_bound(merged: Dict[rd.ResourceId, BoundTexture], found: List[BoundTexture]) -> None:
    for bound in found:
        merged[bound.resource_id] = bound


def _find_action_in_tree(actions, eid: int):
    for action in actions or []:
        if int(getattr(action, "eventId", 0) or 0) == eid:
            return action
        found = _find_action_in_tree(getattr(action, "children", None), eid)
        if found is not None:
            return found
    return None


def find_draw_action(controller, pyrenderdoc_, eid: int):
    draw = pyrenderdoc_.GetAction(eid)
    if draw is not None:
        return draw
    return _find_action_in_tree(controller.GetRootActions(), eid)


def _is_draw_action(action) -> bool:
    return int(getattr(action, "numIndices", 0) or 0) > 0


def _find_previous_draw_eid(draw) -> Optional[int]:
    node = getattr(draw, "previous", None)
    while node is not None:
        if _is_draw_action(node):
            return int(getattr(node, "eventId", 0) or 0)
        node = getattr(node, "previous", None)
    return None


def _collect_draw_bindings_with_slot_fallback(
    controller,
    draw_eid: int,
    prev_draw_eid: Optional[int],
    texture_names: dict,
    get_shader: Callable,
    expected: Set[Tuple[str, str]],
) -> Tuple[List[BoundTexture], Optional[int]]:
    """
    优先使用当前 Draw EID 的管线绑定；仅对缺失的 shader 贴图槽向前回溯。
    导出内容应对应当前 Draw 执行前的最终绑定，而非区间内首个绑定事件。
    """
    draw_only = _collect_broad_at_eid(
        controller, draw_eid, texture_names, get_shader
    )
    resolved: Dict[Tuple[str, str], BoundTexture] = {}
    _merge_bound_by_slot(
        resolved, _filter_to_shader_texture_slots(draw_only, expected)
    )

    missing = expected - set(resolved.keys())
    if not missing and resolved:
        return list(resolved.values()), draw_eid

    if not missing and draw_only:
        return draw_only, draw_eid

    start = (
        prev_draw_eid + 1
        if prev_draw_eid is not None and 0 < prev_draw_eid < draw_eid
        else max(1, draw_eid - _BIND_LOOKBACK)
    )
    fallback_eid: Optional[int] = None

    for eid in range(draw_eid - 1, start - 1, -1):
        found = _collect_broad_at_eid(controller, eid, texture_names, get_shader)
        slot_hits = _filter_to_shader_texture_slots(found, missing)
        if slot_hits and fallback_eid is None:
            fallback_eid = eid
        for bound in slot_hits:
            key = (bound.stage, bound.bind_name)
            if key not in resolved:
                resolved[key] = bound
                missing.discard(key)
        if not missing:
            break

    if resolved:
        return list(resolved.values()), draw_eid

    if draw_only:
        return draw_only, draw_eid

    return [], fallback_eid


def _expected_shader_texture_keys(
    get_shader: Callable, draw_state
) -> Set[Tuple[str, str]]:
    keys: Set[Tuple[str, str]] = set()
    for stage in _SHADER_STAGES:
        shader_id = draw_state.GetShader(stage)
        if shader_id == rd.ResourceId.Null():
            continue
        try:
            refl = get_shader(shader_id)
        except Exception:
            continue
        if refl is None:
            continue
        for res in getattr(refl, "readOnlyResources", None) or []:
            if not getattr(res, "isTexture", True):
                continue
            name = str(getattr(res, "name", "") or "")
            if name:
                keys.add((_stage_label(stage), name))
    return keys


def _filter_to_shader_texture_slots(
    textures: List[BoundTexture],
    expected: Set[Tuple[str, str]],
) -> List[BoundTexture]:
    """只保留当前 shader reflection 声明的贴图槽（解决曾成功版本导出过多的问题）。"""
    if not expected:
        return textures
    return [t for t in textures if (t.stage, t.bind_name) in expected]


def collect_bound_textures_from_ui(pyrenderdoc_) -> List[BoundTexture]:
    try:
        state = pyrenderdoc_.CurPipelineState()
    except Exception:
        return []
    if state is None:
        return []

    texture_names = _texture_names_from_ui(pyrenderdoc_)

    def get_shader(shader_id):
        return pyrenderdoc_.GetShader(shader_id)

    merged: Dict[rd.ResourceId, BoundTexture] = {}
    _merge_bound(
        merged,
        _collect_from_readonly_resources(state, texture_names, None, get_shader),
    )
    _merge_bound(
        merged,
        _collect_from_all_used_descriptors(state, texture_names, None, get_shader),
    )
    return list(merged.values())


def collect_bound_textures_for_draw(
    controller, pyrenderdoc_, draw, draw_eid: int
) -> Tuple[List[BoundTexture], Optional[int], Optional[int]]:
    texture_names = _texture_names_from_controller(controller)

    def get_shader(shader_id):
        return controller.GetShader(shader_id)

    controller.SetFrameEvent(draw_eid, True)
    draw_state = controller.GetPipelineState()
    expected = _expected_shader_texture_keys(get_shader, draw_state)

    prev_draw_eid = _find_previous_draw_eid(draw)
    textures, export_eid = _collect_draw_bindings_with_slot_fallback(
        controller,
        draw_eid,
        prev_draw_eid,
        texture_names,
        get_shader,
        expected,
    )
    return textures, prev_draw_eid, export_eid


def collect_bound_textures_for_eid(
    controller,
    pyrenderdoc_,
    eid: int,
    ui_bindings: Optional[List[BoundTexture]] = None,
) -> Tuple[List[BoundTexture], Optional[int], Optional[int]]:
    draw_eid = int(eid)
    draw = find_draw_action(controller, pyrenderdoc_, draw_eid)
    if draw is None:
        return list(ui_bindings or []), None, None

    replay_bindings, prev_draw_eid, binding_eid = collect_bound_textures_for_draw(
        controller, pyrenderdoc_, draw, draw_eid
    )

    controller.SetFrameEvent(draw_eid, True)
    draw_state = controller.GetPipelineState()

    def get_shader(shader_id):
        return controller.GetShader(shader_id)

    expected = _expected_shader_texture_keys(get_shader, draw_state)

    merged: Dict[Tuple[str, str], BoundTexture] = {}
    _merge_bound_by_slot(merged, replay_bindings)
    _merge_bound_by_slot(merged, ui_bindings or [])

    filtered = _filter_to_shader_texture_slots(list(merged.values()), expected)
    if filtered:
        return filtered, prev_draw_eid, binding_eid

    if merged:
        return list(merged.values()), prev_draw_eid, binding_eid

    return [], prev_draw_eid, binding_eid


def safe_texture_stem(label: str, stage: str, resource_id: rd.ResourceId) -> str:
    text = label.strip() or ("ResourceId_%s" % int(resource_id))
    text = re.sub(r'[<>:"/\\|?*\s]+', "_", text)
    text = text.strip("._")
    if not text:
        text = "ResourceId_%s" % int(resource_id)
    return "%s_%s" % (stage, text)

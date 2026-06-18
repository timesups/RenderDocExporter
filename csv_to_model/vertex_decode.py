"""顶点解码：按 compType 选择 Float / UNorm / SNorm / UInt(asfloat) 等路径。"""

import math
import struct

import renderdoc as rd

from .util import DECODE_FLOAT, DECODE_INT, DECODE_UINT, normalize_decode_mode

VALID_DECODE_MODES = frozenset((DECODE_FLOAT, DECODE_UINT, DECODE_INT))


def element_size(fmt):
    try:
        size = int(fmt.ElementSize())
        if size > 0:
            return size
    except Exception:
        pass
    return int(fmt.compByteWidth) * int(fmt.compCount)


def _uint_as_shader_float(u, bit_width=32):
    """
    HLSL asfloat：把整型位模式写入 float。
    FBX 等仅支持 float 顶点属性时，着色器对读到的 float 做 asuint 可还原原 uint（32 位内）。
    """
    bw = min(int(bit_width), 32)
    mask = (1 << bw) - 1 if bw < 32 else 0xFFFFFFFF
    bits = int(u) & mask
    return struct.unpack("<f", struct.pack("<I", bits))[0]


def _uint_tuple_as_shader_float(values, bit_width=32):
    return tuple(_uint_as_shader_float(v, bit_width) for v in values)


def _has_bad_float(value):
    for v in value:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return True
    return False


def _fit_comp_count(value, count):
    count = int(count)
    if count < len(value):
        return value[:count]
    if count > len(value):
        return value + (0.0,) * (count - len(value))
    return value


def _float_char(byte_width):
    chars = "xxexfxxxd"
    if byte_width < 0 or byte_width >= len(chars):
        return None
    ch = chars[byte_width]
    return None if ch == "x" else ch


def _uint_char(byte_width):
    chars = "xBHxIxxxL"
    if byte_width < 0 or byte_width >= len(chars):
        return None
    ch = chars[byte_width]
    return None if ch == "x" else ch


def _signed_char(byte_width):
    chars = "xbhxixxl"
    if byte_width < 0 or byte_width >= len(chars):
        return None
    ch = chars[byte_width]
    return None if ch == "x" else ch


def _comp_type(fmt):
    try:
        return fmt.compType
    except Exception:
        return None


def _apply_bgra_order(fmt, value):
    if fmt.BGRAOrder() and len(value) >= 4:
        return tuple(value[i] for i in [2, 1, 0, 3])
    return value


def _read_regular_raw(fmt, data):
    byte_width = int(fmt.compByteWidth)
    comp_count = int(fmt.compCount)
    ch = _uint_char(byte_width)
    if ch is None:
        for bw in (4, 2, 1, 8):
            ch = _uint_char(bw)
            if ch is not None:
                byte_width = bw
                break
    if ch is None:
        return None, None

    vertex_format = str(comp_count) + ch
    if struct.calcsize(vertex_format) > len(data):
        return None, None

    return struct.unpack_from(vertex_format, data, 0), byte_width


def _signed_from_unsigned(u, bit_width):
    bits = int(u) & ((1 << bit_width) - 1)
    sign = 1 << (bit_width - 1)
    if bits & sign:
        bits -= 1 << bit_width
    return bits


def _half_bits_to_float(h):
    h = int(h) & 0xFFFF
    sign = (h >> 15) & 1
    exp = (h >> 10) & 0x1F
    mant = h & 0x3FF
    if exp == 0:
        if mant == 0:
            return -0.0 if sign else 0.0
        val = (mant / 1024.0) * (2 ** -14)
        return -val if sign else val
    if exp == 31:
        if mant == 0:
            return float("-inf") if sign else float("inf")
        return float("nan")
    val = (1.0 + mant / 1024.0) * (2 ** (exp - 15))
    return -val if sign else val


# --- Regular：Float → UInt ---


def _decode_regular_float(fmt, data):
    byte_width = int(fmt.compByteWidth)
    comp_count = int(fmt.compCount)
    ch = _float_char(byte_width)
    if ch is None:
        raise RuntimeError("无法按 Float 解码")

    vertex_format = str(comp_count) + ch
    if struct.calcsize(vertex_format) > len(data):
        raise RuntimeError("顶点数据长度不足")

    value = tuple(float(v) for v in struct.unpack_from(vertex_format, data, 0))
    return _apply_bgra_order(fmt, value)


def _decode_regular_unorm(fmt, data):
    raw, byte_width = _read_regular_raw(fmt, data)
    if raw is None:
        raise RuntimeError("无法按 UNorm 解码")

    bit_width = byte_width * 8
    max_val = float((1 << bit_width) - 1)
    value = tuple(float(v) / max_val for v in raw)
    return _apply_bgra_order(fmt, value)


def _decode_regular_snorm(fmt, data):
    raw, byte_width = _read_regular_raw(fmt, data)
    if raw is None:
        raise RuntimeError("无法按 SNorm 解码")

    bit_width = byte_width * 8
    denom = float((1 << (bit_width - 1)) - 1)
    value = tuple(
        max(-1.0, min(1.0, _signed_from_unsigned(v, bit_width) / denom))
        for v in raw
    )
    return _apply_bgra_order(fmt, value)


def _decode_regular_sint(fmt, data):
    byte_width = int(fmt.compByteWidth)
    comp_count = int(fmt.compCount)
    ch = _signed_char(byte_width)
    if ch is None:
        raw, byte_width = _read_regular_raw(fmt, data)
        if raw is None:
            raise RuntimeError("无法按 SInt 解码")
        bit_width = byte_width * 8
        value = tuple(float(_signed_from_unsigned(v, bit_width)) for v in raw)
        return _apply_bgra_order(fmt, value)

    vertex_format = str(comp_count) + ch
    if struct.calcsize(vertex_format) > len(data):
        raise RuntimeError("顶点数据长度不足")

    value = tuple(float(v) for v in struct.unpack_from(vertex_format, data, 0))
    return _apply_bgra_order(fmt, value)


def _decode_regular_uint(fmt, data):
    raw, byte_width = _read_regular_raw(fmt, data)
    if raw is None:
        return None

    bit_width = byte_width * 8
    value = _uint_tuple_as_shader_float(raw, bit_width)
    return _apply_bgra_order(fmt, value)


def _decode_regular(fmt, data):
    comp_type = _comp_type(fmt)

    if comp_type in (rd.CompType.UNorm, rd.CompType.UNormSRGB):
        return _decode_regular_unorm(fmt, data)
    if comp_type == rd.CompType.SNorm:
        return _decode_regular_snorm(fmt, data)
    if comp_type == rd.CompType.UInt:
        value = _decode_regular_uint(fmt, data)
        if value is None:
            raise RuntimeError("无法按 UInt 解码")
        return value
    if comp_type == rd.CompType.SInt:
        return _decode_regular_sint(fmt, data)
    if comp_type in (rd.CompType.UScaled, rd.CompType.SScaled):
        raw, _byte_width = _read_regular_raw(fmt, data)
        if raw is None:
            raise RuntimeError("无法按 Scaled 整型解码")
        return _apply_bgra_order(fmt, tuple(float(v) for v in raw))

    try:
        value = _decode_regular_float(fmt, data)
    except Exception:
        value = (float("nan"),)

    # Typeless / Depth / 未知：保留 Float 失败时 asfloat 回退（着色器位模式）
    if _has_bad_float(value) and comp_type in (
        None,
        rd.CompType.Typeless,
        rd.CompType.Depth,
    ):
        alt = _decode_regular_uint(fmt, data)
        if alt is not None:
            value = alt

    return value


# --- Special：Float 语义 → UInt 位域 ---


def _decode_r10g10b10a2_float(raw):
    v = struct.unpack_from("<I", raw, 0)[0]
    return (
        (v & 0x3FF) / 1023.0,
        ((v >> 10) & 0x3FF) / 1023.0,
        ((v >> 20) & 0x3FF) / 1023.0,
        ((v >> 30) & 0x3) / 3.0,
    )


def _decode_r10g10b10a2_uint(raw):
    v = struct.unpack_from("<I", raw, 0)[0]
    return (
        _uint_as_shader_float(v & 0x3FF, 10),
        _uint_as_shader_float((v >> 10) & 0x3FF, 10),
        _uint_as_shader_float((v >> 20) & 0x3FF, 10),
        _uint_as_shader_float((v >> 30) & 0x3, 2),
    )


def _decode_r11g11b10_float(raw):
    v = struct.unpack_from("<I", raw, 0)[0]
    return (
        _half_bits_to_float((v << 4) & 0x7FF0),
        _half_bits_to_float((v >> 7) & 0x7FF0),
        _half_bits_to_float((v >> 17) & 0x7FE0),
    )


def _decode_r11g11b10_uint(raw):
    v = struct.unpack_from("<I", raw, 0)[0]
    return (
        _uint_as_shader_float(v & 0x7FF, 11),
        _uint_as_shader_float((v >> 11) & 0x7FF, 11),
        _uint_as_shader_float((v >> 22) & 0x3FF, 10),
    )


def _decode_r5g6b5_float(raw):
    v = struct.unpack_from("<H", raw, 0)[0]
    return (
        (v & 0x1F) / 31.0,
        ((v >> 5) & 0x3F) / 63.0,
        ((v >> 11) & 0x1F) / 31.0,
    )


def _decode_r5g6b5_uint(raw):
    v = struct.unpack_from("<H", raw, 0)[0]
    return (
        _uint_as_shader_float(v & 0x1F, 5),
        _uint_as_shader_float((v >> 5) & 0x3F, 6),
        _uint_as_shader_float((v >> 11) & 0x1F, 5),
    )


def _decode_r5g5b5a1_float(raw):
    v = struct.unpack_from("<H", raw, 0)[0]
    return (
        ((v >> 10) & 0x1F) / 31.0,
        ((v >> 5) & 0x1F) / 31.0,
        (v & 0x1F) / 31.0,
        ((v >> 15) & 0x1) / 1.0,
    )


def _decode_r4g4b4a4_float(raw):
    v = struct.unpack_from("<H", raw, 0)[0]
    return (
        ((v >> 12) & 0xF) / 15.0,
        ((v >> 8) & 0xF) / 15.0,
        ((v >> 4) & 0xF) / 15.0,
        (v & 0xF) / 15.0,
    )


def _decode_r4g4_float(raw):
    v = raw[0] if raw else 0
    return (
        ((v >> 4) & 0xF) / 15.0,
        (v & 0xF) / 15.0,
    )


def _decode_r9g9b9e5_float(raw):
    v = struct.unpack_from("<I", raw, 0)[0]
    exp_shared = (v >> 27) & 0x1F
    if exp_shared == 31:
        return (float("nan"), float("nan"), float("nan"))
    scale = 2.0 ** (exp_shared - 15 - 9)
    return (
        (v & 0x1FF) * scale,
        ((v >> 9) & 0x1FF) * scale,
        ((v >> 18) & 0x1FF) * scale,
    )


def _decode_r9g9b9e5_uint(raw):
    v = struct.unpack_from("<I", raw, 0)[0]
    return (
        _uint_as_shader_float(v & 0x1FF, 9),
        _uint_as_shader_float((v >> 9) & 0x1FF, 9),
        _uint_as_shader_float((v >> 18) & 0x1FF, 9),
    )


def _decode_special_float(fmt, data):
    fmt_type = fmt.type
    if fmt_type == rd.ResourceFormatType.R10G10B10A2:
        return _decode_r10g10b10a2_float(data)
    if fmt_type == rd.ResourceFormatType.R11G11B10:
        return _decode_r11g11b10_float(data)
    if fmt_type == rd.ResourceFormatType.R5G6B5:
        return _decode_r5g6b5_float(data)
    if fmt_type == rd.ResourceFormatType.R5G5B5A1:
        return _decode_r5g5b5a1_float(data)
    if fmt_type == rd.ResourceFormatType.R4G4B4A4:
        return _decode_r4g4b4a4_float(data)
    if fmt_type == rd.ResourceFormatType.R4G4:
        return _decode_r4g4_float(data)
    if fmt_type == rd.ResourceFormatType.R9G9B9E5:
        return _decode_r9g9b9e5_float(data)
    if fmt_type == rd.ResourceFormatType.A8:
        return ((data[0] / 255.0,) if data else (0.0,))
    raise RuntimeError(
        "不支持的顶点打包格式: %s"
        % (fmt.Name() if hasattr(fmt, "Name") else fmt_type)
    )


def _decode_special_uint(fmt, data):
    fmt_type = fmt.type
    if fmt_type == rd.ResourceFormatType.R10G10B10A2:
        return _decode_r10g10b10a2_uint(data)
    if fmt_type == rd.ResourceFormatType.R11G11B10:
        return _decode_r11g11b10_uint(data)
    if fmt_type == rd.ResourceFormatType.R5G6B5:
        return _decode_r5g6b5_uint(data)
    if fmt_type == rd.ResourceFormatType.R9G9B9E5:
        return _decode_r9g9b9e5_uint(data)
    if fmt_type == rd.ResourceFormatType.A8:
        return (_uint_as_shader_float(data[0] if data else 0, 8),)
    # 其余打包格式 UInt 回退：整字按 asfloat 写入单通道
    if fmt_type in (
        rd.ResourceFormatType.R5G5B5A1,
        rd.ResourceFormatType.R4G4B4A4,
        rd.ResourceFormatType.R4G4,
    ):
        size = element_size(fmt)
        if size >= 4:
            v = struct.unpack_from("<I", data, 0)[0]
            return (_uint_as_shader_float(v, 32),)
        if size >= 2:
            v = struct.unpack_from("<H", data, 0)[0]
            return (_uint_as_shader_float(v, 16),)
        return (_uint_as_shader_float(data[0] if data else 0, 8),)
    return None


def _decode_special_int(fmt, data):
    fmt_type = fmt.type
    if fmt_type == rd.ResourceFormatType.A8:
        v = data[0] if data else 0
        if v >= 128:
            v -= 256
        return (float(v),)
    try:
        return _decode_regular_sint(fmt, data)
    except Exception:
        pass
    try:
        return _decode_special_float(fmt, data)
    except Exception:
        return (float("nan"),)


def unpack_vertex_data(fmt, data, decode_mode=DECODE_FLOAT):
    """按 RenderDoc compType 或用户指定的 decode_mode 解包顶点分量。"""
    decode_mode = normalize_decode_mode(decode_mode)
    size = element_size(fmt)
    if size <= 0:
        raise RuntimeError("无效的顶点属性格式大小")
    chunk = bytes(data[:size])
    count = int(fmt.compCount)

    if fmt.Special():
        if decode_mode == DECODE_UINT:
            value = _decode_special_uint(fmt, chunk)
            if value is None:
                value = (float("nan"),)
        elif decode_mode == DECODE_INT:
            value = _decode_special_int(fmt, chunk)
        else:
            try:
                value = _decode_special_float(fmt, chunk)
            except Exception:
                value = (float("nan"),)
            if _has_bad_float(value) and _comp_type(fmt) == rd.CompType.UInt:
                alt = _decode_special_uint(fmt, chunk)
                if alt is not None:
                    value = alt
        return _fit_comp_count(value, count)

    if decode_mode == DECODE_UINT:
        value = _decode_regular_uint(fmt, chunk)
        if value is None:
            value = (float("nan"),)
    elif decode_mode == DECODE_INT:
        try:
            value = _decode_regular_sint(fmt, chunk)
        except Exception:
            value = (float("nan"),)
    else:
        try:
            value = _decode_regular(fmt, chunk)
        except Exception:
            value = (float("nan"),)

    return _fit_comp_count(value, count)

"""문자 단위 정규화 도우미: 특수기호·첨자·기호 글꼴·글자 대비·파일명 키.

원칙
- 저장하는 본문은 원문 문자를 유지한다(℃를 °C로 바꾸지 않는다). 비교·검색용 키에서만 호환 정규화를 쓴다.
- 의미가 바뀌는 정규화는 하지 않는다. 예: 파일명 키에서 '-70℃'의 부호, '±'는 지우지 않는다.
"""
import re
import unicodedata

# ---------------------------------------------------------------- Symbol 글꼴

# Word '기호 삽입'·PowerPoint 기호 글꼴은 문자를 유니코드가 아닌 글꼴 코드(0x20~0xFF, 저장 시 F0xx)로 둔다.
# Adobe Symbol 인코딩 기준. 괄호 조각처럼 단독 의미가 약한 코드는 넣지 않는다(미변환으로 보고).
_SYMBOL_FONT = {
    0x20: " ", 0x21: "!", 0x22: "∀", 0x23: "#", 0x24: "∃", 0x25: "%", 0x26: "&", 0x27: "∋", 0x28: "(", 0x29: ")",
    0x2A: "∗", 0x2B: "+", 0x2C: ",", 0x2D: "−", 0x2E: ".", 0x2F: "/", 0x3A: ":", 0x3B: ";", 0x3C: "<", 0x3D: "=",
    0x3E: ">", 0x3F: "?", 0x40: "≅",
    0x41: "Α", 0x42: "Β", 0x43: "Χ", 0x44: "Δ", 0x45: "Ε", 0x46: "Φ", 0x47: "Γ", 0x48: "Η", 0x49: "Ι", 0x4A: "ϑ",
    0x4B: "Κ", 0x4C: "Λ", 0x4D: "Μ", 0x4E: "Ν", 0x4F: "Ο", 0x50: "Π", 0x51: "Θ", 0x52: "Ρ", 0x53: "Σ", 0x54: "Τ",
    0x55: "Υ", 0x56: "ς", 0x57: "Ω", 0x58: "Ξ", 0x59: "Ψ", 0x5A: "Ζ", 0x5B: "[", 0x5C: "∴", 0x5D: "]", 0x5E: "⊥",
    0x5F: "_", 0x61: "α", 0x62: "β", 0x63: "χ", 0x64: "δ", 0x65: "ε", 0x66: "φ", 0x67: "γ", 0x68: "η", 0x69: "ι",
    0x6A: "ϕ", 0x6B: "κ", 0x6C: "λ", 0x6D: "μ", 0x6E: "ν", 0x6F: "ο", 0x70: "π", 0x71: "θ", 0x72: "ρ", 0x73: "σ",
    0x74: "τ", 0x75: "υ", 0x76: "ϖ", 0x77: "ω", 0x78: "ξ", 0x79: "ψ", 0x7A: "ζ", 0x7B: "{", 0x7C: "|", 0x7D: "}",
    0x7E: "∼", 0xA0: "€", 0xA1: "ϒ", 0xA2: "′", 0xA3: "≤", 0xA4: "⁄", 0xA5: "∞", 0xA6: "ƒ", 0xA7: "♣", 0xA8: "♦",
    0xA9: "♥", 0xAA: "♠", 0xAB: "↔", 0xAC: "←", 0xAD: "↑", 0xAE: "→", 0xAF: "↓", 0xB0: "°", 0xB1: "±", 0xB2: "″",
    0xB3: "≥", 0xB4: "×", 0xB5: "∝", 0xB6: "∂", 0xB7: "•", 0xB8: "÷", 0xB9: "≠", 0xBA: "≡", 0xBB: "≈", 0xBC: "…",
    0xBF: "↵", 0xC0: "ℵ", 0xC1: "ℑ", 0xC2: "ℜ", 0xC3: "℘", 0xC4: "⊗", 0xC5: "⊕", 0xC6: "∅", 0xC7: "∩", 0xC8: "∪",
    0xC9: "⊃", 0xCA: "⊇", 0xCB: "⊄", 0xCC: "⊂", 0xCD: "⊆", 0xCE: "∈", 0xCF: "∉", 0xD0: "∠", 0xD1: "∇", 0xD2: "®",
    0xD3: "©", 0xD4: "™", 0xD5: "∏", 0xD6: "√", 0xD7: "⋅", 0xD8: "¬", 0xD9: "∧", 0xDA: "∨", 0xDB: "⇔", 0xDC: "⇐",
    0xDD: "⇑", 0xDE: "⇒", 0xDF: "⇓", 0xE0: "◊", 0xE1: "〈", 0xE2: "®", 0xE3: "©", 0xE4: "™", 0xE5: "∑", 0xF1: "〉",
    0xF2: "∫",
}
_SYMBOL_FONTS = {"symbol", "symbol mt", "standardsymbolsps"}
_DIGITS = {ord(str(d)): str(d) for d in range(10)}


def symbol_font_char(font: str | None, code: int) -> str | None:
    """기호 글꼴 코드를 유니코드로 바꾼다. 모르는 글꼴(Wingdings 등)이나 코드는 None."""
    if (font or "").strip().casefold() not in _SYMBOL_FONTS:
        return None
    if 0xF000 <= code <= 0xF0FF:
        code -= 0xF000
    if 0x30 <= code <= 0x39:
        return _DIGITS[code]
    return _SYMBOL_FONT.get(code)


def is_symbol_font(font: str | None) -> bool:
    return (font or "").strip().casefold() in _SYMBOL_FONTS


def map_symbol_font_text(font: str | None, text: str) -> tuple[str, int]:
    """기호 글꼴로 쓴 사설 영역(F0xx) 글자를 유니코드로 바꾼다. (결과, 바꾼 개수)"""
    if not is_symbol_font(font):
        return text, 0
    changed, out = 0, []
    for ch in text:
        mapped = symbol_font_char(font, ord(ch)) if 0xF020 <= ord(ch) <= 0xF0FF else None
        if mapped is not None:
            changed += 1
        out.append(mapped if mapped is not None else ch)
    return "".join(out), changed


# ---------------------------------------------------------------- 위·아래첨자

_SUP = dict(zip("0123456789+-−=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ⁿⁱ"))
_SUB = dict(zip("0123456789+-−=()", "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎"))


def to_script(text: str, kind: str) -> str | None:
    """서식 첨자를 유니코드 첨자로 바꾼다. 모든 글자를 바꿀 수 있을 때만 결과를 준다(부분 변환은 의미를 흐린다)."""
    table = _SUP if kind == "sup" else _SUB
    body = text.strip()
    if not body or any(ch not in table for ch in body):
        return None
    return text.replace(body, "".join(table[ch] for ch in body))


# ---------------------------------------------------------------- 특수기호 분류

def _is_plain(ch: str) -> bool:
    code = ord(ch)
    return (code < 128 or ch.isspace()
            or 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F  # 한글
            or 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0xF900 <= code <= 0xFAFF  # 한자
            or 0x3000 <= code <= 0x303F)  # 한중일 문장 부호(、。「」 등)


def is_special(ch: str) -> bool:
    """측정 대상 특수기호: ASCII·한글·한자·공백이 아닌 글자. 사설 영역(기호 글꼴 잔여)도 포함한다."""
    return not _is_plain(ch) and unicodedata.category(ch) not in ("Cc", "Cf", "Mn")


def special_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ch in text:
        if is_special(ch):
            counts[ch] = counts.get(ch, 0) + 1
    return counts


def compatibility_form(ch: str) -> str | None:
    """'℃'→'°C', '²'→'2'처럼 호환 정규화로 바뀌는 글자면 바뀐 형태를 준다."""
    folded = unicodedata.normalize("NFKC", ch)
    return folded if folded != ch else None


# ---------------------------------------------------------------- 글자 대비

def _luminance(hex_color: str) -> float:
    value = hex_color.strip().lstrip("#")
    value = value[-6:]
    channels = []
    for i in (0, 2, 4):
        c = int(value[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def parse_hex_color(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lstrip("#")
    if re.fullmatch(r"[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8}", value):
        return value[-6:].upper()
    return None


def contrast_ratio(foreground: str, background: str = "FFFFFF") -> float:
    """WCAG 대비. 1이면 배경과 같은 색, 21이면 흰 바탕의 검은 글자."""
    a, b = _luminance(foreground), _luminance(background)
    high, low = max(a, b), min(a, b)
    return round((high + 0.05) / (low + 0.05), 2)


LOW_CONTRAST = 1.6  # D9D9D9(1.41)·F2F2F2(1.12)는 걸리고 BFBFBF(1.84)는 걸리지 않는다.


# ---------------------------------------------------------------- 파일명

_INVISIBLE = dict.fromkeys(map(ord, "\u200b\ufeff\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"))
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−﹘﹣－"), "-")
_DEGREES = {ord("˚"): "°", ord("º"): "°", ord("⁰"): "°"}
# 부호로 보는 붙임표: 맨 앞·공백·괄호 뒤의 '-숫자', 또는 온도처럼 '-숫자°'. '보고서-2026'의 붙임표는 구분자다.
_SIGN = re.compile(r"(?:^|(?<=[\s(\[{~_,;]))-(?=\d)|-(?=\d+(?:\.\d+)?\s*°)")
_KEEP = set("°±∓−+%‰≥≤<>")


def display_name(name: str) -> str:
    """표시용 파일명: macOS에서 온 분해형 한글(NFD)을 조합형(NFC)으로, 방향 제어·폭 없는 글자는 뺀다.
    의미 있는 기호(℃, ±, −)는 그대로 둔다."""
    return unicodedata.normalize("NFC", name.translate(_INVISIBLE))


def name_key(text: str) -> str:
    """같은 뜻의 이름을 같게, 다른 뜻의 이름을 다르게 만드는 비교 키.

    - '−70°C'·'-70℃'·'－70˚C'는 같다. 'm²'와 'm2'도 같다(호환 정규화).
    - '-70℃'와 '70℃', '±0.5'와 '0.5'는 다르다(부호·기호를 지우지 않는다).
    - 공백·밑줄·구분용 붙임표 등 나머지 기호는 비교에서 뺀다.
    """
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE).translate(_DASHES).translate(_DEGREES)
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _SIGN.sub("−", text)
    return "".join(ch for ch in text if ch in _KEEP or (ch.isalnum() or unicodedata.category(ch) == "Mn"))

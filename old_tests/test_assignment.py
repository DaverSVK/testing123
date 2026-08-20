"""
Static analysis tests for Assignment 2 – VRS cvicenie 2 (edge detection + debounce)
Target MCU: STM32F303K8Tx (Cortex-M4)

Builds on assignment 1 – the GPIO/RCC register macros are still required, therefore
those checks are kept as prerequisites.

Checks performed WITHOUT compiling – pure text/regex analysis of:
  - Inc/assignment.h   (macro definitions, EDGE_TYPE enum, edgeDetect prototype)
  - Src/main.c         (GPIO init code, edgeDetect definition, LED toggle on one edge)

Expected register map (STM32F303K8, RM0316 reference manual):
  GPIOA base  : 0x48000000
  GPIOA MODER : 0x48000000  (offset 0x00)
  GPIOA OTYPER: 0x48000004  (offset 0x04)
  GPIOA OSPEEDR:0x48000008  (offset 0x08)
  GPIOA PUPDR : 0x4800000C  (offset 0x0C)
  GPIOA IDR   : 0x48000010  (offset 0x10)
  GPIOA ODR   : 0x48000014  (offset 0x14)
  GPIOA BSRR  : 0x48000018  (offset 0x18)
  GPIOA BRR   : 0x48000028  (offset 0x28)
  RCC  base   : 0x40021000
  RCC  AHBENR : 0x40021014  (offset 0x14)

Assignment pin requirements:
  PA3 – input  (button / edge source)
  PA4 – output (LED, toggles on the detected edge)

Assignment 2 requirements:
  EDGE_TYPE enum  : NONE = 0, RISE = 1, FALL = 2
  edgeDetect      : EDGE_TYPE edgeDetect(uint8_t pin_state, uint8_t samples);
  debounce window : SAMPLE_PERIOD_MS * DEBOUNCE_SAMPLES = 100 ms
"""

import re
import sys
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT    = Path(__file__).resolve().parent.parent
ASSIGNMENT_H = REPO_ROOT / "Inc" / "assignment.h"
MAIN_C       = REPO_ROOT / "Src" / "main.c"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    assert path.exists(), f"File not found: {path}"
    return path.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """Remove C-style block and line comments so regex hits clean tokens."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def _get_macro_value(source: str, macro_name: str) -> str | None:
    """
    Return the expansion text of a #define after removing its comments.
    Returns None if the macro is not defined or has an empty body.
    """
    clean = _strip_comments(source)
    # Match:  #define MACRO_NAME   <rest of line>
    pattern = rf"^\s*#\s*define\s+{re.escape(macro_name)}\s+(.*?)\s*$"
    m = re.search(pattern, clean, re.MULTILINE)
    if not m:
        return None
    value = m.group(1).strip()
    return value if value else None


def _contains_hex(text: str, addr: int, tolerance_bits: int = 0) -> bool:
    """Return True if any hex literal in text equals addr (case-insensitive)."""
    for m in re.finditer(r"0[xX][0-9a-fA-F]+", text):
        val = int(m.group(), 16)
        if val == addr:
            return True
    return False


def _contains_bit(text: str, bit: int) -> bool:
    """
    Return True if text references bit <bit> via:
      (1 << bit)  |  (1u << bit)  |  (1UL << bit)  |  hex literal 1<<bit
    """
    hex_val = 1 << bit
    if _contains_hex(text, hex_val):
        return True
    # (1 << N) pattern with optional spaces, u/U/L suffixes
    pattern = rf"\(1[uUlL]*\s*<<\s*{bit}\s*\)"
    if re.search(pattern, text):
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 1 – File existence
# ═══════════════════════════════════════════════════════════════════════════════

def test_assignment_h_exists():
    """Inc/assignment.h must be present in the repository."""
    assert ASSIGNMENT_H.exists(), f"Missing file: {ASSIGNMENT_H}"


def test_main_c_exists():
    """Src/main.c must be present in the repository."""
    assert MAIN_C.exists(), f"Missing file: {MAIN_C}"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 2 – Macro definitions are not empty
# ═══════════════════════════════════════════════════════════════════════════════

REQUIRED_MACROS = [
    "GPIOA_BASE_ADDR",
    "GPIOA_MODER_REG",
    "GPIOA_OTYPER_REG",
    "GPIOA_OSPEEDER_REG",
    "GPIOA_PUPDR_REG",
    "GPIOA_IDR_REG",
    "GPIOA_ODR_REG",
    "GPIOA_BSRR_REG",
    "GPIOA_BRR_REG",
    "RCC_BASE_ADDR",
    "RCC_AHBENR_REG",
    "LED_ON",
    "LED_OFF",
    "BUTTON_GET_STATE",
]


def _make_macro_defined_test(macro: str):
    def test():
        src = _read(ASSIGNMENT_H)
        val = _get_macro_value(src, macro)
        assert val is not None, (
            f"Macro '{macro}' in assignment.h is either missing or has an "
            f"empty body. Every macro must be given a concrete implementation."
        )
    test.__name__ = f"test_macro_defined__{macro}"
    test.__doc__  = f"Macro {macro} must be defined with a non-empty value."
    return test


# Dynamically create one test per macro
for _macro in REQUIRED_MACROS:
    _fn = _make_macro_defined_test(_macro)
    globals()[_fn.__name__] = _fn


# ═══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 3 – Correct GPIOA base address (0x48000000)
# ═══════════════════════════════════════════════════════════════════════════════

GPIOA_BASE = 0x48000000

def test_gpioa_base_address_correct():
    """GPIOA_BASE_ADDR must contain the hex literal 0x48000000."""
    src  = _read(ASSIGNMENT_H)
    val  = _get_macro_value(src, "GPIOA_BASE_ADDR")
    assert val is not None, "GPIOA_BASE_ADDR is not defined."
    assert _contains_hex(val, GPIOA_BASE), (
        f"GPIOA_BASE_ADDR = '{val}' – expected 0x48000000 "
        f"(STM32F303K8 reference manual, section 3.3 Memory map)."
    )


def test_gpioa_base_present_in_register_macros():
    """
    Register address macros must be derived from GPIOA_BASE_ADDR or contain the
    base address literal 0x48000000. At least IDR and ODR are checked.
    """
    src = _read(ASSIGNMENT_H)
    clean = _strip_comments(src)

    for reg_macro in ("GPIOA_IDR_REG", "GPIOA_ODR_REG", "GPIOA_MODER_REG"):
        val = _get_macro_value(src, reg_macro)
        assert val is not None, f"{reg_macro} is not defined."
        # Either references the base macro name or contains the literal
        uses_base = (
            "GPIOA_BASE_ADDR" in val
            or _contains_hex(val, GPIOA_BASE)
        )
        assert uses_base, (
            f"{reg_macro} = '{val}' – must be derived from GPIOA_BASE_ADDR "
            f"or contain 0x48000000."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 4 – Register offsets are plausible for STM32F303
# ═══════════════════════════════════════════════════════════════════════════════

_EXPECTED_OFFSETS = {
    "GPIOA_MODER_REG":    0x00,
    "GPIOA_OTYPER_REG":   0x04,
    "GPIOA_OSPEEDER_REG": 0x08,
    "GPIOA_PUPDR_REG":    0x0C,
    "GPIOA_IDR_REG":      0x10,
    "GPIOA_ODR_REG":      0x14,
    "GPIOA_BSRR_REG":     0x18,
    "GPIOA_BRR_REG":      0x28,
}


def test_register_absolute_addresses():
    """
    For each GPIO register macro, the absolute address
    (GPIOA_BASE + offset) must appear somewhere in the file.
    """
    src = _read(ASSIGNMENT_H)
    full_text = _strip_comments(src)

    for macro, offset in _EXPECTED_OFFSETS.items():
        expected_addr = GPIOA_BASE + offset
        # Check the whole file – the address might be in the macro body
        # or computed from GPIOA_BASE_ADDR which itself holds 0x48000000
        val = _get_macro_value(src, macro)
        assert val is not None, f"{macro} is not defined."

        addr_present = _contains_hex(full_text, expected_addr)
        uses_base    = "GPIOA_BASE_ADDR" in val

        assert addr_present or uses_base, (
            f"{macro} = '{val}' – expected address 0x{expected_addr:08X} "
            f"(GPIOA base 0x{GPIOA_BASE:08X} + offset 0x{offset:02X}) "
            f"to appear in file, or macro must reference GPIOA_BASE_ADDR."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 5 – RCC / AHBENR correct addresses
# ═══════════════════════════════════════════════════════════════════════════════

RCC_BASE   = 0x40021000
RCC_AHBENR = 0x40021014   # RCC base + 0x14


def test_rcc_base_address_correct():
    """RCC_BASE_ADDR must contain 0x40021000."""
    src = _read(ASSIGNMENT_H)
    val = _get_macro_value(src, "RCC_BASE_ADDR")
    assert val is not None, "RCC_BASE_ADDR is not defined."
    assert _contains_hex(val, RCC_BASE), (
        f"RCC_BASE_ADDR = '{val}' – expected 0x40021000 "
        f"(STM32F303K8 RM0316 §3.3 – RCC registers start at 0x40021000)."
    )


def test_rcc_ahbenr_address_correct():
    """RCC_AHBENR_REG must resolve to 0x40021014 (base + 0x14)."""
    src  = _read(ASSIGNMENT_H)
    full = _strip_comments(src)
    val  = _get_macro_value(src, "RCC_AHBENR_REG")
    assert val is not None, "RCC_AHBENR_REG is not defined."

    addr_present = _contains_hex(full, RCC_AHBENR)
    uses_rcc     = "RCC_BASE_ADDR" in val

    assert addr_present or uses_rcc, (
        f"RCC_AHBENR_REG = '{val}' – expected 0x40021014 (RCC base + 0x14) "
        f"to appear in file, or macro must reference RCC_BASE_ADDR."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 6 – LED macros use PA4 (bit 4)
# ═══════════════════════════════════════════════════════════════════════════════

LED_BIT = 4   # PA4

def test_led_on_uses_pin4():
    """LED_ON must reference bit 4 (PA4) – either as (1<<4), 0x10, or 0x00100000."""
    src = _read(ASSIGNMENT_H)
    val = _get_macro_value(src, "LED_ON")
    assert val is not None, "LED_ON is not defined."
    # Bit 4 in ODR → 0x10  |  bit 4 in BSRR set → 0x10  | (1<<4)
    # Bit 4+16=20 in BSRR reset → 0x100000 is for LED_OFF via BSRR
    assert _contains_bit(val, LED_BIT) or _contains_hex(val, 1 << LED_BIT), (
        f"LED_ON = '{val}' – must set bit {LED_BIT} (PA4). "
        f"Expected (1<<{LED_BIT}) or 0x{1<<LED_BIT:X} in the macro body."
    )


def test_led_off_uses_pin4():
    """LED_OFF must reference bit 4 (PA4) in any valid form."""
    src = _read(ASSIGNMENT_H)
    val = _get_macro_value(src, "LED_OFF")
    assert val is not None, "LED_OFF is not defined."

    # Possible encodings:
    #  ODR:  ~(1<<4)  or  0xFFFFFFEF
    #  BSRR: (1 << (4+16)) = 0x100000
    #  BRR:  (1 << 4)  = 0x10
    bit4_direct  = _contains_bit(val, LED_BIT) or _contains_hex(val, 1 << LED_BIT)
    bsrr_reset   = _contains_bit(val, LED_BIT + 16) or _contains_hex(val, 1 << (LED_BIT + 16))

    assert bit4_direct or bsrr_reset, (
        f"LED_OFF = '{val}' – must clear bit {LED_BIT} (PA4). "
        f"Expected (1<<{LED_BIT}), 0x{1<<LED_BIT:X}, "
        f"or BSRR reset bit (1<<{LED_BIT+16}) = 0x{1<<(LED_BIT+16):X}."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 7 – BUTTON_GET_STATE uses PA3 (bit 3)
# ═══════════════════════════════════════════════════════════════════════════════

BUTTON_BIT = 3   # PA3

def test_button_get_state_uses_pin3():
    """BUTTON_GET_STATE must read bit 3 (PA3) from the IDR register."""
    src = _read(ASSIGNMENT_H)
    val = _get_macro_value(src, "BUTTON_GET_STATE")
    assert val is not None, "BUTTON_GET_STATE is not defined."

    assert _contains_bit(val, BUTTON_BIT) or _contains_hex(val, 1 << BUTTON_BIT), (
        f"BUTTON_GET_STATE = '{val}' – must test bit {BUTTON_BIT} (PA3). "
        f"Expected (1<<{BUTTON_BIT}) or 0x{1<<BUTTON_BIT:X}."
    )


def test_button_get_state_uses_idr():
    """BUTTON_GET_STATE must read the IDR register (not ODR or BSRR)."""
    src = _read(ASSIGNMENT_H)
    val = _get_macro_value(src, "BUTTON_GET_STATE")
    assert val is not None, "BUTTON_GET_STATE is not defined."

    uses_idr = "GPIOA_IDR_REG" in val or _contains_hex(val, GPIOA_BASE + 0x10)

    assert uses_idr, (
        f"BUTTON_GET_STATE = '{val}' – must read GPIOA_IDR_REG "
        f"(address 0x48000010) to obtain button state. "
        f"Reading ODR or BSRR for input is incorrect."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 8 – main.c has non-empty GPIO init sections
# ═══════════════════════════════════════════════════════════════════════════════

def test_main_c_has_clock_enable_code():
    """
    Src/main.c must contain actual code enabling the GPIOA clock via RCC_AHBENR.
    The comment placeholder alone is not sufficient.
    """
    src   = _read(MAIN_C)
    clean = _strip_comments(src)

    # Look for the section between the two comment anchors
    clock_section_pattern = (
        r"Enable clock for GPIO port A"  # comment marker in main.c
        r".*?"
        r"GPIOA pins? \d+ and \d+ setup"  # next section marker
    )
    m = re.search(clock_section_pattern, src, re.DOTALL | re.IGNORECASE)

    if m:
        section = _strip_comments(m.group(0))
    else:
        section = clean   # fall back to full file scan

    # Must contain a write to any of: RCC_AHBENR_REG macro, or raw address
    has_rcc_write = (
        "RCC_AHBENR_REG" in section
        or _contains_hex(section, RCC_AHBENR)
        or _contains_hex(section, RCC_BASE)
    )
    assert has_rcc_write, (
        "main.c appears to have no RCC AHBENR clock-enable code. "
        "Add a write to RCC_AHBENR_REG to enable the GPIOA peripheral clock "
        "(bit 17 – IOPAEN)."
    )


def test_main_c_has_gpio_moder_config():
    """
    Src/main.c must configure GPIOA MODER to set PA3=input and PA4=output.
    Checks that GPIOA_MODER_REG (or its address) is written in main.c.
    """
    src   = _read(MAIN_C)
    clean = _strip_comments(src)

    has_moder = (
        "GPIOA_MODER_REG" in clean
        or _contains_hex(clean, GPIOA_BASE + 0x00)
    )
    assert has_moder, (
        "main.c appears to have no GPIOA MODER configuration. "
        "Write to GPIOA_MODER_REG to configure PA3 as input (bits 7:6 = 00) "
        "and PA4 as output (bits 9:8 = 01)."
    )


def test_main_c_uses_macros_not_raw_literals():
    """
    main.c should reference macros from assignment.h rather than raw
    register addresses. This checks that at least LED_ON / LED_OFF /
    BUTTON_GET_STATE appear in main.c (they are already in the template).
    """
    src = _read(MAIN_C)
    assert "LED_ON" in src,           "LED_ON macro not found in main.c."
    assert "LED_OFF" in src,          "LED_OFF macro not found in main.c."
    assert "BUTTON_GET_STATE" in src, "BUTTON_GET_STATE macro not found in main.c."


def test_main_c_does_not_write_whole_register():
    """
    The assignment explicitly states 'DO NOT WRITE TO THE WHOLE REGISTER'.
    Check that the student is not doing simple full-register assignments like
       *GPIOA_MODER_REG = 0x...;
    inside the init section (bit-masking with |= or &= is required).
    """
    src   = _read(MAIN_C)
    clean = _strip_comments(src)

    # Find the init section (between Systick init and while(1))
    init_section_m = re.search(
        r"LL_SetSystemCoreClock.*?while\s*\(\s*1\s*\)",
        clean, re.DOTALL
    )
    if not init_section_m:
        return   # Can't isolate section – skip this structural check

    init = init_section_m.group(0)

    # Pattern: *MACRO_REG = literal;   (full assignment without masking)
    bad_pattern = re.compile(
        r"\*\s*\w+_REG\s*=\s*0[xX][0-9a-fA-F]+\s*;",
    )
    matches = bad_pattern.findall(init)
    assert not matches, (
        "main.c contains full register write(s) without bit masking: "
        + ", ".join(matches)
        + ". Use |= and &= with appropriate masks instead."
    )

# ═══════════════════════════════════════════════════════════════════════════════
# ASSIGNMENT 2 – helpers
# ═══════════════════════════════════════════════════════════════════════════════

EXPECTED_DEBOUNCE_MS = 100

# EDGE_TYPE edgeDetect(uint8_t pin_state, uint8_t samples)
_EDGE_DETECT_SIGNATURE = (
    r"EDGE_TYPE\s+edgeDetect\s*\(\s*uint8_t\s+(\w+)\s*,\s*uint8_t\s+(\w+)\s*\)"
)


def _int_literal(text: str) -> int | None:
    """Parse a C integer literal such as '100', '100U', '0x64UL' – None if not one."""
    m = re.fullmatch(r"\(?\s*(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*\)?", text.strip())
    if not m:
        return None
    return int(m.group(1), 0)


def _find_macro_anywhere(macro: str) -> str | None:
    """Look for a #define in assignment.h first, then in main.c."""
    for path in (ASSIGNMENT_H, MAIN_C):
        if not path.exists():
            continue
        val = _get_macro_value(_read(path), macro)
        if val is not None:
            return val
    return None


def _matching_brace_body(text: str, open_index: int) -> str | None:
    """Return the text between the '{' at open_index and its matching '}'."""
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_index + 1:i]
    return None


def _get_enum_body(source: str, enum_name: str) -> str | None:
    """
    Return the body of an enum, accepting both
        typedef enum { ... } EDGE_TYPE;
    and
        enum EDGE_TYPE { ... };
    """
    clean = _strip_comments(source)

    m = re.search(
        rf"typedef\s+enum\s*(?:\w+\s*)?\{{(.*?)\}}\s*{re.escape(enum_name)}\s*;",
        clean, re.DOTALL
    )
    if m:
        return m.group(1)

    m = re.search(rf"enum\s+{re.escape(enum_name)}\s*\{{(.*?)\}}", clean, re.DOTALL)
    if m:
        return m.group(1)

    return None


def _parse_enum_values(body: str) -> dict:
    """
    Map enumerator name -> value. Handles explicit '= n' as well as implicit
    positional numbering (NONE, RISE, FALL  ->  0, 1, 2).
    """
    values = {}
    next_val = 0
    for item in body.split(","):
        item = item.strip()
        if not item:
            continue
        m = re.match(r"^(\w+)\s*(?:=\s*(0[xX][0-9a-fA-F]+|\d+))?$", item)
        if not m:
            continue
        if m.group(2) is not None:
            next_val = int(m.group(2), 0)
        values[m.group(1)] = next_val
        next_val += 1
    return values


def _edge_detect_definition(source: str):
    """
    Return ((pin_param, samples_param), body) for the edgeDetect definition,
    or None when the function is not defined in this file.
    """
    clean = _strip_comments(source)
    m = re.search(_EDGE_DETECT_SIGNATURE + r"\s*\{", clean)
    if not m:
        return None
    body = _matching_brace_body(clean, m.end() - 1)
    if body is None:
        return None
    return (m.group(1), m.group(2)), body


def _main_loop_body(source: str) -> str | None:
    """Return the body of the 'while (1)' loop inside main()."""
    clean = _strip_comments(source)
    m = re.search(r"while\s*\(\s*1\s*\)\s*\{", clean)
    if not m:
        return None
    return _matching_brace_body(clean, m.end() - 1)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 9 – EDGE_TYPE enum
# ═══════════════════════════════════════════════════════════════════════════════

def test_edge_type_enum_defined():
    """assignment.h must define an enum named EDGE_TYPE."""
    body = _get_enum_body(_read(ASSIGNMENT_H), "EDGE_TYPE")
    assert body is not None, (
        "No 'EDGE_TYPE' enum found in Inc/assignment.h. Define it as "
        "'typedef enum { NONE = 0, RISE = 1, FALL = 2 } EDGE_TYPE;'."
    )


def test_edge_type_enum_values():
    """EDGE_TYPE must enumerate NONE = 0, RISE = 1, FALL = 2."""
    body = _get_enum_body(_read(ASSIGNMENT_H), "EDGE_TYPE")
    assert body is not None, "EDGE_TYPE enum is not defined in Inc/assignment.h."

    values = _parse_enum_values(body)

    for name, expected in (("NONE", 0), ("RISE", 1), ("FALL", 2)):
        assert name in values, (
            f"Enumerator '{name}' missing from EDGE_TYPE. "
            f"Found: {sorted(values)}. Required: NONE, RISE, FALL."
        )
        assert values[name] == expected, (
            f"EDGE_TYPE.{name} = {values[name]} – expected {expected}. "
            f"Required values: NONE = 0, RISE = 1, FALL = 2."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 10 – edgeDetect declaration and definition
# ═══════════════════════════════════════════════════════════════════════════════

def test_edge_detect_declared_in_header():
    """
    assignment.h must declare
        EDGE_TYPE edgeDetect(uint8_t pin_state, uint8_t samples);
    """
    clean = _strip_comments(_read(ASSIGNMENT_H))
    assert re.search(_EDGE_DETECT_SIGNATURE + r"\s*;", clean), (
        "Prototype 'EDGE_TYPE edgeDetect(uint8_t pin_state, uint8_t samples);' "
        "not found in Inc/assignment.h. Both parameters must be of type uint8_t "
        "and the return type must be EDGE_TYPE."
    )


def test_edge_detect_defined_in_main():
    """Src/main.c must define edgeDetect with the required signature and a real body."""
    definition = _edge_detect_definition(_read(MAIN_C))
    assert definition is not None, (
        "Definition of 'EDGE_TYPE edgeDetect(uint8_t pin_state, uint8_t samples)' "
        "not found in Src/main.c."
    )
    _, body = definition
    assert len(body.strip()) > 20, (
        "The body of edgeDetect in Src/main.c is empty or trivial – "
        "the edge detection logic must be implemented there."
    )


def test_edge_detect_keeps_state():
    """
    edgeDetect gets one sample per call, so the previous pin state and the counter
    of identical samples have to survive between calls – i.e. 'static' variables
    (or file-scope variables) are required.
    """
    src = _read(MAIN_C)
    definition = _edge_detect_definition(src)
    assert definition is not None, "edgeDetect is not defined in Src/main.c."

    _, body = definition
    if "static" in body:
        return

    # File-scope variables declared before the function are acceptable too.
    clean = _strip_comments(src)
    before = clean.split("EDGE_TYPE")[0]
    assert re.search(r"\b(?:static\s+|volatile\s+)*u?int\d*_t\s+\w+\s*(?:=|;)", before), (
        "edgeDetect does not keep any state between calls. One call processes one "
        "sample, so the last stable pin state and the counter of identical samples "
        "must be stored in 'static' (or global) variables."
    )


def test_edge_detect_uses_samples_argument():
    """The 'samples' parameter must actually be used inside edgeDetect."""
    definition = _edge_detect_definition(_read(MAIN_C))
    assert definition is not None, "edgeDetect is not defined in Src/main.c."

    (pin_param, samples_param), body = definition

    assert re.search(rf"\b{re.escape(samples_param)}\b", body), (
        f"Parameter '{samples_param}' is never used in edgeDetect. The new pin state "
        f"must be read '{samples_param}'-times in a row before an edge is reported."
    )
    assert re.search(rf"\b{re.escape(pin_param)}\b", body), (
        f"Parameter '{pin_param}' is never used in edgeDetect – the current pin state "
        f"has to be evaluated."
    )


def test_edge_detect_returns_rise_and_fall():
    """edgeDetect must be able to report both RISE and FALL."""
    definition = _edge_detect_definition(_read(MAIN_C))
    assert definition is not None, "edgeDetect is not defined in Src/main.c."

    _, body = definition
    for enumerator in ("RISE", "FALL"):
        assert re.search(rf"\b{enumerator}\b", body), (
            f"edgeDetect never reports '{enumerator}'. The function has to "
            f"distinguish a rising edge (RISE) from a falling one (FALL)."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 11 – debounce window and main() application
# ═══════════════════════════════════════════════════════════════════════════════

def test_debounce_window_is_100ms():
    """
    The sampling period multiplied by the number of samples must give the required
    debounce window of 100 ms:  SAMPLE_PERIOD_MS * DEBOUNCE_SAMPLES = 100.
    """
    period_raw = _find_macro_anywhere("SAMPLE_PERIOD_MS")
    samples_raw = _find_macro_anywhere("DEBOUNCE_SAMPLES")

    assert period_raw is not None, (
        "Macro 'SAMPLE_PERIOD_MS' (period of one input pin sample in ms) is not defined."
    )
    assert samples_raw is not None, (
        "Macro 'DEBOUNCE_SAMPLES' (number of identical samples required) is not defined."
    )

    period = _int_literal(period_raw)
    samples = _int_literal(samples_raw)

    assert period is not None, f"SAMPLE_PERIOD_MS = '{period_raw}' is not an integer literal."
    assert samples is not None, f"DEBOUNCE_SAMPLES = '{samples_raw}' is not an integer literal."
    assert period > 0, "SAMPLE_PERIOD_MS must be greater than zero."
    assert 0 < samples < 256, (
        f"DEBOUNCE_SAMPLES = {samples} – the 'samples' argument is a uint8_t, "
        f"so the value must fit in 1..255."
    )

    window = period * samples
    assert window == EXPECTED_DEBOUNCE_MS, (
        f"Debounce window is {window} ms (SAMPLE_PERIOD_MS = {period} ms * "
        f"DEBOUNCE_SAMPLES = {samples}) – expected {EXPECTED_DEBOUNCE_MS} ms."
    )


def test_main_calls_edge_detect():
    """The application loop in main() must call edgeDetect."""
    loop = _main_loop_body(_read(MAIN_C))
    assert loop is not None, "No 'while (1)' application loop found in Src/main.c."

    assert re.search(r"\bedgeDetect\s*\(", loop), (
        "edgeDetect is never called inside the 'while (1)' loop of main(). "
        "The input pin has to be sampled and evaluated in the application loop."
    )


def test_main_samples_button_with_period():
    """
    The loop must sample the input pin periodically – the sampling period defines
    the debounce time, so a delay of SAMPLE_PERIOD_MS has to be present in the loop.
    """
    loop = _main_loop_body(_read(MAIN_C))
    assert loop is not None, "No 'while (1)' application loop found in Src/main.c."

    assert "BUTTON_GET_STATE" in loop, (
        "The input pin state (BUTTON_GET_STATE) is not read inside the application loop."
    )
    assert re.search(r"LL_mDelay\s*\(", loop), (
        "No LL_mDelay() call inside the application loop – without a defined sampling "
        "period the debounce window is undefined."
    )


def test_main_toggles_led_on_single_edge():
    """
    The LED must change its state (On -> Off, Off -> On) only for ONE chosen edge
    type – either RISE or FALL, not both.
    """
    loop = _main_loop_body(_read(MAIN_C))
    assert loop is not None, "No 'while (1)' application loop found in Src/main.c."

    uses_rise = bool(re.search(r"\bRISE\b", loop))
    uses_fall = bool(re.search(r"\bFALL\b", loop))

    assert uses_rise or uses_fall, (
        "The result of edgeDetect is not compared against RISE nor FALL in main(). "
        "The LED must change its state only when the chosen edge type is detected."
    )
    assert not (uses_rise and uses_fall), (
        "The application loop reacts to both RISE and FALL. The assignment requires "
        "the LED to change its state for only ONE chosen edge type."
    )
    assert "LED_ON" in loop and "LED_OFF" in loop, (
        "Both LED_ON and LED_OFF must be used in the application loop – the LED has "
        "to toggle its state (On -> Off, Off -> On) on every detected edge."
    )

"""
Static analysis tests for Assignment 1 – VRS cvicenie 1
Target MCU: STM32F303K8Tx (Cortex-M4)

Checks performed WITHOUT compiling – pure text/regex analysis of:
  - Inc/assignment.h   (macro definitions)
  - Src/main.c         (GPIO init code presence)

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
  PA3 – input  (button)
  PA4 – output (LED)
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

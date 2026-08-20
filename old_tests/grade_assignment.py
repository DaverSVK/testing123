"""
Grading for Assignment 2 - VRS cvicenie 2 (edge detection + debounce), 3 points total.

  0.5 b  EDGE_TYPE enum (NONE = 0, RISE = 1, FALL = 2)
  0.5 b  edgeDetect declared in assignment.h and defined in main.c
  1.0 b  debounce window of 100 ms really works (verified on the Raspberry Pi)
  1.0 b  LED changes its state only on the chosen edge type (verified on the Raspberry Pi)

Static and binary groups are graded by pytest, the two hardware backed groups by the
result file produced by hw_debounce_test.py on the self-hosted Raspberry Pi runner.
"""

import json
import subprocess
import sys
from pathlib import Path

# Directory this script lives in - "tests/" in CI, "old_tests/" when run locally.
TESTS_DIR = Path(__file__).resolve().parent

HARDWARE_RESULTS = Path("hardware-results.json")

TOTAL_POINTS = 3.0


def t(name: str) -> str:
    """pytest node id in test_assignment.py"""
    return f"{TESTS_DIR / 'test_assignment.py'}::{name}"


def b(name: str) -> str:
    """pytest node id in test_binary.py"""
    return f"{TESTS_DIR / 'test_binary.py'}::{name}"


GRADE_GROUPS = [
    {
        "name": "EDGE_TYPE enum (NONE = 0, RISE = 1, FALL = 2)",
        "points": 0.5,
        "pytest": [
            t("test_edge_type_enum_defined"),
            t("test_edge_type_enum_values"),
        ],
        "hardware": [],
    },
    {
        "name": "edgeDetect declared and defined",
        "points": 0.5,
        "pytest": [
            t("test_edge_detect_declared_in_header"),
            t("test_edge_detect_defined_in_main"),
            t("test_edge_detect_keeps_state"),
            t("test_edge_detect_uses_samples_argument"),
            t("test_edge_detect_returns_rise_and_fall"),
            b("test_edge_detect_symbol_present"),
            b("test_edge_detect_uses_static_state"),
        ],
        "hardware": [],
    },
    {
        "name": "Debounce 100 ms works (hardware)",
        "points": 1.0,
        "pytest": [
            t("test_debounce_window_is_100ms"),
            t("test_main_samples_button_with_period"),
            b("test_debounce_samples_immediate_in_main"),
            b("test_main_calls_ll_mdelay"),
        ],
        "hardware": ["debounce_reject"],
    },
    {
        "name": "LED changes state on the detected edge (hardware)",
        "points": 1.0,
        "pytest": [
            t("test_main_calls_edge_detect"),
            t("test_main_toggles_led_on_single_edge"),
            b("test_main_calls_edge_detect"),
        ],
        "hardware": ["led_toggle"],
    },
]

# Assignment 1 checks - still required for the program to work, but not graded here.
PREREQUISITES = {
    "name": "GPIO PA3/PA4 setup (cvicenie 1)",
    "points": 0.0,
    "pytest": [
        t("test_main_c_has_clock_enable_code"),
        t("test_main_c_has_gpio_moder_config"),
        t("test_led_on_uses_pin4"),
        t("test_led_off_uses_pin4"),
        t("test_button_get_state_uses_pin3"),
        t("test_button_get_state_uses_idr"),
        b("test_rcc_ahbenr_addr_in_disasm"),
        b("test_rcc_iopaen_bit_value_in_disasm"),
        b("test_led_bit4_value_in_disasm"),
        b("test_button_bit3_value_in_disasm"),
    ],
    "hardware": [],
}


def run_pytest_tests(tests: list) -> bool:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "--disable-warnings",
            "-p", "no:cacheprovider",
            *tests,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    if result.returncode != 0:
        print(result.stdout)

    return result.returncode == 0


def load_hardware_results():
    """Result file written by hw_debounce_test.py on the Raspberry Pi runner."""
    if not HARDWARE_RESULTS.exists():
        return None
    try:
        return json.loads(HARDWARE_RESULTS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"WARNING: cannot read {HARDWARE_RESULTS}: {exc}")
        return None


def evaluate_group(group: dict, hardware) -> bool:
    passed = True

    if group["pytest"]:
        passed = run_pytest_tests(group["pytest"]) and passed

    for key in group["hardware"]:
        if hardware is None:
            print(f"WARNING: no hardware results - '{group['name']}' cannot be awarded.")
            passed = False
        elif hardware.get(key) != "PASS":
            print(f"Hardware check '{key}' = {hardware.get(key)} (expected PASS)")
            passed = False

    return passed


def format_points(value: float) -> str:
    if value == 0:
        return "0b"
    if value == 1:
        return "1b"
    return f"{value:.2f}b"


def colored_points(score: float) -> str:
    points = format_points(score)

    if score > 0:
        return f"✅ **{points}**"

    return f"❌ **{points}**"


def main() -> int:
    # The table uses ✅/❌ - do not let a non-UTF-8 console kill the grading.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

    hardware = load_hardware_results()

    total = 0.0
    results = []

    for group in GRADE_GROUPS:
        passed = evaluate_group(group, hardware)
        score = group["points"] if passed else 0.0
        total += score
        results.append((group["name"], score))

    prerequisites_ok = evaluate_group(PREREQUISITES, hardware)

    print()
    print("## Statistics")
    print()
    print("| Category | Points |")
    print("|---|---:|")

    for name, score in results:
        print(f"| {name} | {colored_points(score)} |")

    print(f"| **Total** | **{total} / {TOTAL_POINTS}** |")

    print()
    print("### Details")
    print()
    print(f"- Prerequisites - {PREREQUISITES['name']}: "
          f"{'✅ OK' if prerequisites_ok else '❌ FAILED'}")

    if hardware is None:
        print("- Hardware test: ❌ no `hardware-results.json` "
              "(the Raspberry Pi job did not produce a result)")
    else:
        print(f"- Hardware test: detected edge type "
              f"**{hardware.get('edge_type_detected')}**, "
              f"debounce window **{hardware.get('debounce_window_ms')} ms**, "
              f"overall **{hardware.get('overall')}**")

        failed = [d for d in hardware.get("details", []) if d.get("result") == "FAIL"]
        for detail in failed:
            print(f"  - ❌ `{detail.get('phase')}/{detail.get('name')}`: "
                  f"{detail.get('info')}")

    return 0 if total == TOTAL_POINTS else 1


if __name__ == "__main__":
    raise SystemExit(main())

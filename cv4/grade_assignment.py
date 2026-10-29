"""
Grading for Assignment 4 - VRS cvicenie 4 (USART2 + DMA), 4 points total.

  0.5 b  DMA and USART peripheral configuration
  1.5 b  USART2_CheckDmaReception - Rx handling without data loss
  1.5 b  proccesDmaData - valid string detection and letter counting
  0.5 b  Periodic DMA Rx buffer state message

There is no all-or-nothing gate in this assignment. The checks that prove the DMA is
really used (no polling of USART2->RDR, Rx channel in normal mode, the interrupt path
installed) live inside the two DMA groups, so a solution that polls the receiver by
hand loses those 2.0 points and can still score the string parsing and the periodic
message. A banner is printed so the reason for the loss is visible.

Static and binary groups are graded by pytest, the hardware backed checks by the result
file produced by hw_usart_test.py on the self-hosted Raspberry Pi runner.
"""

import json
import subprocess
import sys
from pathlib import Path

# Directory this script lives in - "tests/" in CI, "cv4/" when run locally.
TESTS_DIR = Path(__file__).resolve().parent

HARDWARE_RESULTS = Path("hardware-results.json")

TOTAL_POINTS = 4.0


def t(name):
    """pytest node id in test_assignment.py"""
    return "%s::%s" % (TESTS_DIR / "test_assignment.py", name)


def b(name):
    """pytest node id in test_binary.py"""
    return "%s::%s" % (TESTS_DIR / "test_binary.py", name)


GRADE_GROUPS = [
    {
        "name": "DMA and USART peripheral configuration",
        "points": 0.5,
        "pytest": [
            t("test_dma_rx_channel6_configured"),
            t("test_dma_tx_channel7_configured"),
            t("test_dma_rx_mode_is_normal"),
            t("test_dma_rx_direction_periph_to_memory"),
            t("test_dma_tx_direction_memory_to_periph"),
            t("test_dma_rx_memory_increment"),
            t("test_dma_rx_addresses_use_buffer"),
            t("test_dma_rx_length_is_buffer_size"),
            t("test_dma_rx_ht_and_tc_interrupts_enabled"),
            t("test_usart_idle_interrupt_enabled"),
            t("test_usart_dma_requests_enabled"),
            t("test_usart_and_rx_channel_enabled"),
            t("test_main_loop_does_not_poll_the_receiver"),
            t("test_main_does_not_call_check_dma_reception"),
            b("test_dma_and_usart_handlers_not_default"),
            b("test_dma1_channel6_vector_installed"),
            b("test_dma1_channel7_vector_installed"),
            b("test_usart2_vector_installed"),
            b("test_usart2_configured_in_init"),
            b("test_dma1_configured_in_init"),
            b("test_main_does_not_read_rdr"),
        ],
        "hardware": ["link_alive"],
    },
    {
        "name": "USART2_CheckDmaReception - Rx handling without data loss",
        "points": 1.5,
        "pytest": [
            t("test_check_dma_reception_is_not_a_stub"),
            t("test_check_dma_reception_reads_remaining_length"),
            t("test_check_dma_reception_keeps_a_read_index"),
            t("test_check_dma_reception_calls_the_callback"),
            t("test_check_dma_reception_guards_the_buffer_end"),
            t("test_check_dma_reception_rearms_the_channel"),
            t("test_check_dma_reception_does_not_block"),
            b("test_check_dma_reception_present"),
            b("test_check_dma_reception_is_not_empty"),
            b("test_check_dma_reception_reads_transfer_counter"),
            b("test_check_dma_reception_uses_the_rx_buffer"),
            b("test_check_dma_reception_does_not_delay"),
        ],
        "hardware": ["chunked_reception", "no_data_loss"],
    },
    {
        "name": "proccesDmaData - valid string detection and letter counting",
        "points": 1.5,
        "pytest": [
            t("test_process_dma_data_is_not_a_stub"),
            t("test_process_dma_data_uses_frame_delimiters"),
            t("test_process_dma_data_keeps_state_between_calls"),
            t("test_letter_count_global_is_defined"),
            t("test_process_dma_data_classifies_letter_case"),
            t("test_frame_timeout_is_35_characters"),
            t("test_callback_is_registered_in_main"),
            t("test_valid_string_message_format"),
            t("test_valid_string_is_sent_with_putbuffer"),
            b("test_process_dma_data_present"),
            b("test_process_dma_data_is_not_empty"),
            b("test_frame_delimiters_in_binary"),
            b("test_letter_range_bounds_in_binary"),
            b("test_callback_registered_in_main"),
        ],
        "hardware": ["string_parsing"],
    },
    {
        "name": "Periodic DMA Rx buffer state message",
        "points": 0.5,
        "pytest": [
            t("test_buffer_state_message_format"),
            t("test_buffer_state_uses_the_real_dma_state"),
            t("test_periodic_transmission_is_every_two_seconds"),
            b("test_putbuffer_called_from_main"),
            b("test_message_strings_in_binary"),
            b("test_buffer_size_immediate_in_binary"),
            b("test_printf_float_is_linked"),
        ],
        "hardware": ["periodic_message"],
    },
]

# Not scored on their own - the project simply has to build and keep the template intact.
PREREQUISITES = {
    "name": "The project builds and the template files are intact",
    "points": 0.0,
    "pytest": [
        t("test_usart_h_exists"),
        t("test_usart_c_exists"),
        t("test_main_c_exists"),
        t("test_buffer_size_macro_defined"),
        b("test_elf_file_exists"),
        b("test_disassembly_file_exists"),
        b("test_symbols_file_exists"),
        b("test_main_function_present"),
    ],
    "hardware": [],
}

# Report-only: these are the checks that prove the DMA is really doing the work.
# They are already scored inside groups 1 and 2 - this list only drives the banner.
DMA_CHECKS = {
    "name": "The reception really runs on DMA + interrupts",
    "points": 0.0,
    "pytest": [
        t("test_main_loop_does_not_poll_the_receiver"),
        t("test_main_does_not_call_check_dma_reception"),
        t("test_dma_rx_mode_is_normal"),
        b("test_main_does_not_read_rdr"),
        b("test_dma1_configured_in_init"),
    ],
    "hardware": [],
}


def run_pytest_tests(tests):
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
    """Result file written by hw_usart_test.py on the Raspberry Pi runner."""
    if not HARDWARE_RESULTS.exists():
        return None
    try:
        return json.loads(HARDWARE_RESULTS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("WARNING: cannot read %s: %s" % (HARDWARE_RESULTS, exc))
        return None


def evaluate_group(group, hardware, quiet=False):
    passed = True

    if group["pytest"]:
        if quiet:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--tb=no", "--disable-warnings",
                 "-p", "no:cacheprovider", *group["pytest"]],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            passed = result.returncode == 0
        else:
            passed = run_pytest_tests(group["pytest"]) and passed

    for key in group["hardware"]:
        if hardware is None:
            print("WARNING: no hardware results - '%s' cannot be awarded." % group["name"])
            passed = False
        elif hardware.get(key) != "PASS":
            print("Hardware check '%s' = %s (expected PASS)" % (key, hardware.get(key)))
            passed = False

    return passed


def format_points(value):
    if value == 0:
        return "0b"
    if value == 1:
        return "1b"
    return "%.2fb" % value


def colored_points(score):
    points = format_points(score)

    if score > 0:
        return "✅ **%s**" % points

    return "❌ **%s**" % points


def print_hardware_details(hardware):
    """Every failing hardware case with what was sent, expected and received."""
    failed = [d for d in hardware.get("details", []) if d.get("result") == "FAIL"]
    if not failed:
        return

    print()
    print("### Failed hardware checks")
    print()
    for detail in failed:
        print("- ❌ `%s/%s`" % (detail.get("phase"), detail.get("name")))
        sent = detail.get("sent")
        if sent and sent != "<nothing>":
            print("  - sent: `%s`" % sent)
        if detail.get("expected"):
            print("  - expected: `%s`" % detail.get("expected"))
        if detail.get("got"):
            print("  - got: `%s`" % detail.get("got"))
        if detail.get("info"):
            print("  - reason: %s" % detail.get("info"))


def main():
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
    dma_ok = evaluate_group(DMA_CHECKS, hardware, quiet=True)

    print()
    print("## Statistics")
    print()

    if not dma_ok:
        print("> ❌ **The reception does not run on DMA.**")
        print("> The characters must be collected by DMA1 channel 6 into "
              "`bufferUSART2dma` and")
        print("> delivered through the HT/TC/IDLE interrupts. Reading `USART2->RDR` in "
              "the")
        print("> `while (1)` loop, or leaving the Rx channel in circular mode, costs "
              "the two")
        print("> DMA groups below (up to 2 of the 4 points).")
        print()

    print("| Category | Points |")
    print("|---|---:|")

    for name, score in results:
        print("| %s | %s |" % (name, colored_points(score)))

    print("| **Total** | **%s / %s** |" % (total, TOTAL_POINTS))

    print()
    print("### Details")
    print()
    print("- %s: %s"
          % (PREREQUISITES["name"], "✅ OK" if prerequisites_ok else "❌ FAILED"))
    print("- %s: %s" % (DMA_CHECKS["name"], "✅ OK" if dma_ok else "❌ FAILED"))

    if hardware is None:
        print("- Hardware test: ❌ no `hardware-results.json` "
              "(the Raspberry Pi job did not produce a result)")
    else:
        print("- Hardware test: port **%s** at **%s Bd**, buffer **%s bytes**, "
              "periodic message every **%s s**, input edge cases **%s/%s**, "
              "overall **%s**"
              % (hardware.get("port"), hardware.get("baudrate"),
                 hardware.get("buffer_size"), hardware.get("periodic_period_s"),
                 hardware.get("cases_passed"), hardware.get("cases_total"),
                 hardware.get("overall")))
        print_hardware_details(hardware)

    return 0 if total == TOTAL_POINTS else 1


if __name__ == "__main__":
    raise SystemExit(main())

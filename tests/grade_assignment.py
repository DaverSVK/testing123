import subprocess
import sys


GRADE_GROUPS = [
    (
        "Pheriferal clock configured",
        0.25,
        [
            "tests/test_assignment.py::test_main_c_has_clock_enable_code",
            "tests/test_binary.py::test_rcc_ahbenr_addr_in_disasm",
            "tests/test_binary.py::test_rcc_iopaen_bit_value_in_disasm",
        ],
    ),
    (
        "GPIO A4 used correctly",
        0.25,
        [
            "tests/test_assignment.py::test_led_on_uses_pin4",
            "tests/test_assignment.py::test_led_off_uses_pin4",
            "tests/test_assignment.py::test_main_c_has_gpio_moder_config",
            "tests/test_binary.py::test_led_bit4_value_in_disasm",
            "tests/test_binary.py::test_moder_pa4_output_bits_present",
        ],
    ),
    (
        "GPIO A3 used correctly",
        0.25,
        [
            "tests/test_assignment.py::test_button_get_state_uses_pin3",
            "tests/test_assignment.py::test_button_get_state_uses_idr",
            "tests/test_binary.py::test_button_bit3_value_in_disasm",
        ],
    ),
    (
        "Program working as expected",
        0.25,
        [
            "tests/test_assignment.py::test_main_c_uses_macros_not_raw_literals",
            # "tests/test_assignment.py::test_main_c_does_not_write_whole_register",
            "tests/test_binary.py::test_main_function_present",
            "tests/test_binary.py::test_ll_mdelay_present",
            "tests/test_binary.py::test_delay_250ms_in_binary",
            "tests/test_binary.py::test_delay_1000ms_in_binary",
        ],
    ),
]


def run_pytest_tests(tests: list[str]) -> bool:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "--disable-warnings",
            *tests,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    if result.returncode != 0:
        print(result.stdout)

    return result.returncode == 0


def format_points(value: float) -> str:
    if value == 0:
        return "0b"
    if value == 1:
        return "1b"
    return f"{value:.2f}b"


def main() -> int:
    total = 0.0
    results = []

    for name, points, tests in GRADE_GROUPS:
        passed = run_pytest_tests(tests)
        score = points if passed else 0.0
        total += score
        results.append((name, score))

    print()
    print("Statistics")
    print("===================")

    for name, score in results:
        print(f"{name:<35}: {format_points(score)}")

    print("====================")
    print(f"total: {format_points(total)}")

    print()
    print("## Statistics")
    print()
    print("| Category | Points |")
    print("|---|---:|")

    for name, score in results:
        print(f"| {name} | {format_points(score)} |")

    print(f"| **Total** | **{format_points(total)}** |")

    return 0 if total == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
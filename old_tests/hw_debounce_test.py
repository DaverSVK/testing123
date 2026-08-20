#!/usr/bin/env python3
"""
Hardware test for Assignment 2 – VRS cvicenie 2 (edge detection + debounce)

Runs on the self-hosted Raspberry Pi runner with the STM32F303K8 already flashed.

Wiring
  Pi GPIO BUTTON_GPIO (default 17)  ->  STM32 PA3   (input signal / button)
  Pi GPIO LED_GPIO    (default 27)  <-  STM32 PA4   (LED output)

What is verified
  1. Polarity     – which edge type (RISE or FALL) makes the LED change its state.
                    Exactly one of them is allowed, as required by the assignment.
  2. Debounce     – pulses SHORTER than the debounce window (100 ms) must be ignored.
                    This is the core of the test: the input is "woken" with 10/25/50/70 ms
                    pulses and the LED must not react to any of them.
  3. Toggling     – a level held LONGER than the debounce window must toggle the LED
                    (On -> Off, Off -> On), and the opposite edge must not move it.
  4. Boundary     – informational scan around the debounce window, never asserted,
                    because the behaviour exactly at the threshold is timing dependent.

The debounce window is read from Inc/assignment.h (SAMPLE_PERIOD_MS * DEBOUNCE_SAMPLES),
so the test follows the source instead of assuming a fixed value.

Outputs (in the current working directory = repository root):
  hardware-results.json  – machine readable result consumed by grade_assignment.py
  hardware-result.txt    – PASS / FAIL

Exit code: 0 when everything passed, 1 otherwise.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT    = Path(__file__).resolve().parent.parent
ASSIGNMENT_H = REPO_ROOT / "Inc" / "assignment.h"

RESULTS_JSON = Path("hardware-results.json")
RESULT_TXT   = Path("hardware-result.txt")

# ── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_DEBOUNCE_MS = 100

BUTTON_GPIO = int(os.environ.get("BUTTON_GPIO", "17"))   # Pi drives   -> PA3
LED_GPIO    = int(os.environ.get("LED_GPIO", "27"))      # Pi observes <- PA4

# Pulses shorter than the window that must be REJECTED (fraction of the window).
# Capped at 0.7 so that Python sleep jitter can never cross the real threshold.
GLITCH_FRACTIONS = (0.1, 0.25, 0.5, 0.7)

# Informational only – behaviour right at the threshold is legitimately timing dependent.
BOUNDARY_FRACTIONS = (0.9, 1.0, 1.1, 1.5)

VALID_PRESS_REPEATS = 3


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(message: str) -> None:
    print(message, flush=True)


def read_debounce_window_ms() -> int:
    """
    SAMPLE_PERIOD_MS * DEBOUNCE_SAMPLES from Inc/assignment.h.
    Falls back to 100 ms when the macros cannot be parsed.
    """
    try:
        text = ASSIGNMENT_H.read_text(encoding="utf-8")
    except OSError:
        log(f"WARNING: cannot read {ASSIGNMENT_H} - assuming {DEFAULT_DEBOUNCE_MS} ms")
        return DEFAULT_DEBOUNCE_MS

    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)

    def macro(name):
        m = re.search(rf"^\s*#\s*define\s+{name}\s+(.+?)\s*$", text, re.MULTILINE)
        if not m:
            return None
        lit = re.fullmatch(r"\(?\s*(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*\)?", m.group(1).strip())
        return int(lit.group(1), 0) if lit else None

    period  = macro("SAMPLE_PERIOD_MS")
    samples = macro("DEBOUNCE_SAMPLES")

    if not period or not samples:
        log(f"WARNING: SAMPLE_PERIOD_MS / DEBOUNCE_SAMPLES not found in assignment.h - "
            f"assuming {DEFAULT_DEBOUNCE_MS} ms")
        return DEFAULT_DEBOUNCE_MS

    window = period * samples
    log(f"Debounce window from assignment.h: {period} ms * {samples} samples = {window} ms")
    return window


def write_results(results: dict) -> None:
    RESULTS_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
    RESULT_TXT.write_text(results.get("overall", "FAIL") + "\n", encoding="utf-8")


def fail_early(message: str, window_ms: int) -> int:
    log(f"FAIL: {message}")
    write_results({
        "assignment": "cv2",
        "debounce_window_ms": window_ms,
        "edge_type_detected": None,
        "debounce_reject": "FAIL",
        "led_toggle": "FAIL",
        "overall": "FAIL",
        "error": message,
        "details": [],
    })
    return 1


# ── Test ──────────────────────────────────────────────────────────────────────

class DebounceTest:
    def __init__(self, button, led, window_ms):
        self.button = button
        self.led = led
        self.window_ms = window_ms
        # How long to wait for the MCU to process a change and settle.
        self.settle_s = max(3 * window_ms, 400) / 1000.0
        self.details = []

    # ── low level ────────────────────────────────────────────────────────────
    def drive(self, level: int) -> None:
        if level:
            self.button.on()
        else:
            self.button.off()

    def read_led(self) -> int:
        """Majority vote of 5 samples over ~10 ms - immune to a single flaky read."""
        votes = 0
        for _ in range(5):
            votes += 1 if self.led.value else 0
            time.sleep(0.002)
        return 1 if votes >= 3 else 0

    def settle(self) -> None:
        time.sleep(self.settle_s)

    def record(self, phase, name, passed, info):
        self.details.append({
            "phase": phase,
            "name": name,
            "result": "PASS" if passed else "FAIL",
            "info": info,
        })

    # ── phase 1 ──────────────────────────────────────────────────────────────
    def detect_polarity(self):
        """
        Returns "RISE", "FALL" or None. The student may choose either edge type,
        so the rest of the test adapts to whichever one is implemented.
        """
        log("")
        log("--- Phase 1: which edge type changes the LED? ---")

        self.drive(0)
        self.settle()
        low_before = self.read_led()

        self.drive(1)
        self.settle()
        after_high = self.read_led()

        self.drive(0)
        self.settle()
        after_low = self.read_led()

        rising_acts  = after_high != low_before
        falling_acts = after_low != after_high

        log(f"  LED: idle low = {low_before}, after long HIGH = {after_high}, "
            f"after long LOW = {after_low}")

        if rising_acts and falling_acts:
            log("  FAIL: the LED changes its state on BOTH edges")
            self.record("polarity", "single_edge_type", False,
                        "LED toggles on rising and falling edge - assignment allows only one")
            return None

        if not rising_acts and not falling_acts:
            log("  FAIL: the LED never changed its state")
            self.record("polarity", "edge_detected", False,
                        "LED did not react to a level held far longer than the debounce window")
            return None

        edge = "RISE" if rising_acts else "FALL"
        log(f"  Detected edge type: {edge}")
        self.record("polarity", "single_edge_type", True, f"LED reacts to {edge} only")
        return edge

    # ── phase 2 ──────────────────────────────────────────────────────────────
    def test_glitch_rejection(self, active_level, idle_level):
        """Pulses shorter than the debounce window must not move the LED."""
        log("")
        log(f"--- Phase 2: debounce - pulses shorter than {self.window_ms} ms "
            f"must be ignored ---")

        all_ok = True
        self.drive(idle_level)
        self.settle()

        for fraction in GLITCH_FRACTIONS:
            pulse_ms = max(5, int(round(self.window_ms * fraction)))

            before = self.read_led()
            self.drive(active_level)
            time.sleep(pulse_ms / 1000.0)
            self.drive(idle_level)
            self.settle()
            after = self.read_led()

            ok = (after == before)
            all_ok &= ok
            log(f"  {pulse_ms:4d} ms pulse -> LED {before} -> {after}  "
                f"{'OK (ignored)' if ok else 'FAIL (LED reacted)'}")
            self.record("debounce", f"glitch_{pulse_ms}ms", ok,
                        f"LED {before} -> {after}, pulse {pulse_ms} ms < "
                        f"{self.window_ms} ms window")

        log(f"  Result: {'PASS' if all_ok else 'FAIL'}")
        return all_ok

    # ── phase 3 ──────────────────────────────────────────────────────────────
    def test_valid_toggle(self, active_level, idle_level):
        """A level held longer than the window must toggle the LED - and only once."""
        log("")
        log(f"--- Phase 3: presses longer than {self.window_ms} ms must toggle the LED ---")

        all_ok = True
        hold_s = self.settle_s
        self.drive(idle_level)
        self.settle()

        for attempt in range(1, VALID_PRESS_REPEATS + 1):
            before = self.read_led()

            self.drive(active_level)
            time.sleep(hold_s)
            after_press = self.read_led()

            self.drive(idle_level)
            time.sleep(hold_s)
            after_release = self.read_led()

            toggled = after_press != before
            held    = after_release == after_press

            all_ok &= toggled and held
            log(f"  press {attempt}: LED {before} -> {after_press} -> {after_release}  "
                f"toggled={'yes' if toggled else 'NO'} "
                f"stable_on_opposite_edge={'yes' if held else 'NO'}")

            self.record("toggle", f"press_{attempt}_toggles", toggled,
                        f"LED {before} -> {after_press} after {int(hold_s * 1000)} ms hold")
            self.record("toggle", f"press_{attempt}_ignores_opposite_edge", held,
                        f"LED {after_press} -> {after_release} after releasing")

        log(f"  Result: {'PASS' if all_ok else 'FAIL'}")
        return all_ok

    # ── phase 4 ──────────────────────────────────────────────────────────────
    def scan_boundary(self, active_level, idle_level):
        """Informational only - never fails the test."""
        log("")
        log(f"--- Phase 4: boundary scan around {self.window_ms} ms (informational) ---")

        self.drive(idle_level)
        self.settle()

        for fraction in BOUNDARY_FRACTIONS:
            pulse_ms = max(5, int(round(self.window_ms * fraction)))

            before = self.read_led()
            self.drive(active_level)
            time.sleep(pulse_ms / 1000.0)
            self.drive(idle_level)
            self.settle()
            after = self.read_led()

            accepted = after != before
            log(f"  {pulse_ms:4d} ms pulse -> {'accepted' if accepted else 'rejected'}")
            self.details.append({
                "phase": "boundary",
                "name": f"pulse_{pulse_ms}ms",
                "result": "ACCEPTED" if accepted else "REJECTED",
                "info": "informational only",
            })


def main() -> int:
    window_ms = read_debounce_window_ms()

    log(f"Pi GPIO {BUTTON_GPIO} -> PA3 (input signal), "
        f"Pi GPIO {LED_GPIO} <- PA4 (LED)")

    try:
        from gpiozero import DigitalInputDevice, DigitalOutputDevice
    except ImportError as exc:
        return fail_early(f"gpiozero is not available on the runner: {exc}", window_ms)

    try:
        button = DigitalOutputDevice(BUTTON_GPIO, initial_value=False)
        led = DigitalInputDevice(LED_GPIO, pull_up=False)
    except Exception as exc:                      # noqa: BLE001 - report any GPIO problem
        return fail_early(f"cannot open the GPIO pins: {exc}", window_ms)

    test = DebounceTest(button, led, window_ms)
    edge = None
    debounce_ok = False
    toggle_ok = False

    try:
        edge = test.detect_polarity()

        if edge is not None:
            active_level = 1 if edge == "RISE" else 0
            idle_level = 1 - active_level

            debounce_ok = test.test_glitch_rejection(active_level, idle_level)
            toggle_ok = test.test_valid_toggle(active_level, idle_level)
            test.scan_boundary(active_level, idle_level)
        else:
            log("")
            log("Skipping the debounce and toggle phases - no usable edge type detected.")
    finally:
        try:
            button.off()
            button.close()
            led.close()
        except Exception:                          # noqa: BLE001 - cleanup must not mask results
            pass

    overall = debounce_ok and toggle_ok and edge is not None

    results = {
        "assignment": "cv2",
        "debounce_window_ms": window_ms,
        "edge_type_detected": edge,
        "debounce_reject": "PASS" if debounce_ok else "FAIL",
        "led_toggle": "PASS" if toggle_ok else "FAIL",
        "overall": "PASS" if overall else "FAIL",
        "details": test.details,
    }
    write_results(results)

    log("")
    log("--- Summary ---")
    log(f"  edge type detected      : {edge}")
    log(f"  debounce ({window_ms} ms) rejection: {results['debounce_reject']}")
    log(f"  LED toggling            : {results['led_toggle']}")
    log(f"  overall                 : {results['overall']}")

    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())

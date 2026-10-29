#!/usr/bin/env python3
"""
Hardware test for Assignment 4 - VRS cvicenie 4 (USART2 + DMA).

Runs on the self-hosted Raspberry Pi runner with the STM32F303K8 already flashed.

Wiring: none. USART2 (PA2 = Tx, PA15 = Rx) is physically connected to the
ST-LINK/V2-1 on the Nucleo board, which exposes it to the Pi as a USB virtual COM
port (/dev/ttyACM*). It is the same cable openocd flashes through - the CDC
interface is free again as soon as openocd exits.

The firmware is expected to emit two messages:

  every 2 s   Buffer capacity: %d bytes, occupied memory: %d bytes, load [in %]: %f%
  on a frame  Valid string: %s, lower-case: %d, upper-case: %d

Frame rules under test:
  - '#' starts a set of characters, '$' ends it, everything before '#' is ignored
  - a second '#' inside an open frame RESTARTS it
  - if '$' does not arrive within 35 characters of the '#' (the '$' itself counting
    as one of them) the data is discarded and a new '#' is awaited

Outputs, written into the current working directory:
  hardware-result.txt    - PASS / FAIL
  hardware-results.json  - consumed by grade_assignment.py
"""

import glob
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

# -- Configuration ------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent

RESULT_TXT = Path("hardware-result.txt")
RESULT_JSON = Path("hardware-results.json")

DEFAULT_BAUD = 115200
DEFAULT_BUFFER_SIZE = 256

# How long to wait for the reply to one frame.
REPLY_TIMEOUT = 3.0
# How long to listen before concluding that no reply is coming.
NO_REPLY_WINDOW = 2.0
# Settling time after a reset / between test cases.
SETTLE_S = 0.35

# The periodic message must arrive every 2 s (0.5 Hz), tolerance +/- 25 %.
REPORT_PERIOD_S = 2.0
REPORT_TOLERANCE = 0.25

# README: the transmitting side sends at most 20 characters in one burst.
MAX_BURST = 20

VALID_RE = re.compile(
    r"Valid\s+string:\s*(.*?)\s*,\s*"
    r"lower-case:\s*(\d+)\s*,\s*"
    r"upper-case:\s*(\d+)",
    re.IGNORECASE,
)

BUFFER_RE = re.compile(
    r"Buffer\s+capacity:\s*(\d+)\s*bytes\s*,\s*"
    r"occupied\s+memory:\s*(\d+)\s*bytes\s*,\s*"
    r"load\s*\[\s*in\s*%\s*\]\s*:\s*([0-9]+(?:[.,][0-9]+)?)\s*%",
    re.IGNORECASE,
)


def log(message):
    print(message, flush=True)


def shorten(text, limit=70):
    """Readable one-line rendering of what was sent / received."""
    if text is None:
        return "<nothing>"
    if isinstance(text, bytes):
        text = text.decode("ascii", errors="replace")
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    if len(text) > limit:
        head = text[: limit - 12]
        return "%s…(%d chars)" % (head, len(text))
    return text


# -- Reading the student's configuration --------------------------------------

def read_baud():
    """The baud rate the firmware actually configures, from Src/usart.c."""
    path = REPO_ROOT / "Src" / "usart.c"
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log("WARNING: cannot read %s (%s) - assuming %d Bd" % (path, exc, DEFAULT_BAUD))
        return DEFAULT_BAUD

    m = re.search(r"BaudRate\s*=\s*(\d+)", source)
    if not m:
        m = re.search(r"LL_USART_SetBaudRate\s*\([^;]*?,\s*(\d+)\s*\)", source)
    if m:
        return int(m.group(1))

    log("WARNING: no baud rate found in Src/usart.c - assuming %d Bd" % DEFAULT_BAUD)
    return DEFAULT_BAUD


def read_buffer_size():
    """DMA_USART2_BUFFER_SIZE from Inc/usart.h - the capacity the firmware reports."""
    path = REPO_ROOT / "Inc" / "usart.h"
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log("WARNING: cannot read %s (%s) - assuming %d bytes"
            % (path, exc, DEFAULT_BUFFER_SIZE))
        return DEFAULT_BUFFER_SIZE

    m = re.search(r"#\s*define\s+DMA_USART2_BUFFER_SIZE\s+\(?\s*(\d+)", source)
    if m:
        return int(m.group(1))

    log("WARNING: DMA_USART2_BUFFER_SIZE not found - assuming %d bytes"
        % DEFAULT_BUFFER_SIZE)
    return DEFAULT_BUFFER_SIZE


def find_port():
    """The ST-LINK virtual COM port. SERIAL_PORT overrides the discovery."""
    override = os.environ.get("SERIAL_PORT", "").strip()
    if override:
        return override

    patterns = (
        "/dev/serial/by-id/*STLink*",
        "/dev/serial/by-id/*STM32*",
        "/dev/serial/by-id/*ST-LINK*",
        "/dev/ttyACM*",
        "/dev/ttyUSB*",
    )
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]
    return None


# -- Serial plumbing ----------------------------------------------------------

class Board(object):
    """Serial link to the Nucleo with a background reader thread."""

    def __init__(self, port, baud):
        self.port = port
        self.baud = baud
        self._serial = None
        self._text = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def open(self):
        import serial  # imported late so a missing pyserial becomes a graded FAIL
        self._serial = serial.Serial(self.port, self.baud, timeout=0.1)
        try:
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
        except Exception:
            pass
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        while not self._stop.is_set():
            try:
                chunk = self._serial.read(256)
            except Exception:
                break
            if chunk:
                decoded = chunk.decode("ascii", errors="replace")
                with self._lock:
                    self._text += decoded

    def mark(self):
        """Current end of the received text - used as a search starting point."""
        with self._lock:
            return len(self._text)

    def text_since(self, mark):
        with self._lock:
            return self._text[mark:]

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("ascii")
        self._serial.write(data)
        self._serial.flush()

    def write_chunked(self, data, chunk=MAX_BURST, gap=0.05):
        """Send in bursts of at most `chunk` bytes, as the assignment assumes."""
        if isinstance(data, str):
            data = data.encode("ascii")
        for i in range(0, len(data), chunk):
            self._serial.write(data[i:i + chunk])
            self._serial.flush()
            time.sleep(gap)

    def wait_for(self, pattern, timeout, mark):
        """First match of `pattern` in the text received after `mark`, or None."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            m = pattern.search(self.text_since(mark))
            if m:
                return m
            time.sleep(0.02)
        return pattern.search(self.text_since(mark))

    def wait_for_all(self, pattern, count, timeout, mark):
        """Up to `count` matches of `pattern` after `mark`."""
        deadline = time.time() + timeout
        matches = []
        while time.time() < deadline:
            matches = list(pattern.finditer(self.text_since(mark)))
            if len(matches) >= count:
                return matches
            time.sleep(0.02)
        return matches

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass  # cleanup must not mask results


# -- Result accumulation ------------------------------------------------------

class Report(object):
    def __init__(self, port, baud, buffer_size):
        self.data = {
            "assignment": "cv4",
            "port": port,
            "baudrate": baud,
            "buffer_size": buffer_size,
            "link_alive": "FAIL",
            "periodic_message": "FAIL",
            "periodic_period_s": None,
            "string_parsing": "FAIL",
            "chunked_reception": "FAIL",
            "no_data_loss": "FAIL",
            "cases_passed": 0,
            "cases_total": 0,
            "overall": "FAIL",
            "details": [],
        }

    def add(self, phase, name, ok, sent=None, expected=None, got=None, info=""):
        self.data["details"].append({
            "phase": phase,
            "name": name,
            "result": "PASS" if ok else "FAIL",
            "sent": shorten(sent),
            "expected": expected if expected is not None else "",
            "got": shorten(got),
            "info": info,
        })
        status = "PASS" if ok else "FAIL"
        log("  [%s] %s/%s" % (status, phase, name))
        if not ok:
            log("         sent:     %s" % shorten(sent))
            log("         expected: %s" % (expected or ""))
            log("         got:      %s" % shorten(got))
            if info:
                log("         reason:   %s" % info)
        return ok

    def write(self):
        self.data["overall"] = "PASS" if all(
            self.data[key] == "PASS"
            for key in ("link_alive", "periodic_message", "string_parsing",
                        "chunked_reception", "no_data_loss")
        ) else "FAIL"
        RESULT_JSON.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        RESULT_TXT.write_text(self.data["overall"], encoding="utf-8")
        return self.data["overall"] == "PASS"


def fail_early(message, port=None, baud=None, buffer_size=None):
    """Write a fully populated all-FAIL result so grading never sees a missing file."""
    log("FATAL: %s" % message)
    report = Report(port or "<not found>", baud or DEFAULT_BAUD,
                    buffer_size or DEFAULT_BUFFER_SIZE)
    report.add("setup", "serial_link", False,
               sent=None, expected="an open serial link to the Nucleo",
               got=None, info=message)
    report.write()
    return 1


# -- The input edge cases -----------------------------------------------------

def letter_counts(payload):
    lower = sum(1 for c in payload if "a" <= c <= "z")
    upper = sum(1 for c in payload if "A" <= c <= "Z")
    return lower, upper


def build_cases():
    """
    Every case: what to send, and what the firmware must answer.
    `payload` None means no 'Valid string' reply may appear at all.
    """
    cases = []

    def frame(name, send, payload, why=""):
        cases.append({"name": name, "send": send, "payload": payload, "why": why})

    frame("simple_mixed", "#Platn15uborZnakov$", "Platn15uborZnakov",
          "the example from the assignment text")
    frame("all_lower", "#abcdef$", "abcdef", "only small letters")
    frame("all_upper", "#ABCDEF$", "ABCDEF", "only capital letters")
    frame("digits_only", "#123456$", "123456",
          "digits are neither small nor capital letters")
    frame("empty_frame", "#$", "", "a frame with no characters between '#' and '$'")
    frame("punctuation", "#a-B_c.D!$", "a-B_c.D!",
          "punctuation must not be counted as a letter")
    frame("whitespace_inside", "#a B c$", "a B c",
          "spaces are part of the set of characters")
    frame("junk_before_start", "garbage!!#aBc$", "aBc",
          "everything received before the '#' is ignored")
    frame("no_start_char", "abcDEF$", None,
          "a set of characters terminated by '$' but never opened by '#' must be "
          "ignored completely")
    frame("end_without_start", "$$$", None,
          "a bare '$' with no preceding '#' must not produce anything")
    frame("restart_on_second_hash", "#abc#DEF$", "DEF",
          "a second '#' restarts the set of characters")

    # 35-character window, the closing '$' counting as one of the 35.
    ok_payload = "B" * 34
    frame("timeout_boundary_valid", "#" + ok_payload + "$", ok_payload,
          "34 characters plus the '$' is exactly the 35 character limit")

    too_long = "C" * 35
    frame("timeout_exceeded", "#" + too_long + "$", None,
          "the '$' arrives as the 36th character, so the data must be discarded")

    return cases


def run_frame_cases(board, report):
    cases = build_cases()
    passed = 0

    for case in cases:
        # Close any frame the previous case deliberately left open.
        board.write("$")
        time.sleep(SETTLE_S)
        mark = board.mark()

        board.write(case["send"])

        if case["payload"] is None:
            match = board.wait_for(VALID_RE, NO_REPLY_WINDOW, mark)
            ok = match is None
            expected = "no 'Valid string' message at all"
            got = match.group(0) if match else "<nothing, as required>"
            info = "" if ok else (
                "the firmware answered although %s" % case["why"]
            )
        else:
            lower, upper = letter_counts(case["payload"])
            match = board.wait_for(VALID_RE, REPLY_TIMEOUT, mark)
            expected = "Valid string: %s, lower-case: %d, upper-case: %d" % (
                case["payload"], lower, upper)
            if match is None:
                ok = False
                got = "<timeout: no reply within %.1f s>" % REPLY_TIMEOUT
                info = "no 'Valid string' message arrived - %s" % case["why"]
            else:
                got = match.group(0)
                got_payload = match.group(1)
                got_lower = int(match.group(2))
                got_upper = int(match.group(3))
                problems = []
                if got_payload != case["payload"]:
                    problems.append("the reported string is '%s' instead of '%s'"
                                    % (got_payload, case["payload"]))
                if got_lower != lower:
                    problems.append("lower-case is %d instead of %d" % (got_lower, lower))
                if got_upper != upper:
                    problems.append("upper-case is %d instead of %d" % (got_upper, upper))
                ok = not problems
                info = "" if ok else "; ".join(problems) + " - " + case["why"]

        if report.add("string_parsing", case["name"], ok,
                      sent=case["send"], expected=expected, got=got, info=info):
            passed += 1

    # Recovery after a discarded frame - a separate two-step case.
    board.write("$")
    time.sleep(SETTLE_S)
    mark = board.mark()
    board.write("#" + "D" * 35 + "$")
    time.sleep(0.4)
    board.write("#Ok$")
    matches = board.wait_for_all(VALID_RE, 1, REPLY_TIMEOUT, mark)
    expected = "exactly one reply: Valid string: Ok, lower-case: 1, upper-case: 1"
    if not matches:
        ok, got, info = False, "<timeout: no reply within %.1f s>" % REPLY_TIMEOUT, (
            "after discarding an over-long frame the firmware must start looking for a "
            "new '#' again - the following valid frame was never answered"
        )
    elif len(matches) > 1:
        ok, got = False, " || ".join(m.group(0) for m in matches)
        info = ("the discarded over-long frame was answered as well - only the second, "
                "valid frame may produce a reply")
    else:
        got = matches[0].group(0)
        ok = (matches[0].group(1) == "Ok"
              and int(matches[0].group(2)) == 1
              and int(matches[0].group(3)) == 1)
        info = "" if ok else "the recovered frame was reported incorrectly"

    total = len(cases) + 1
    if report.add("string_parsing", "recover_after_timeout", ok,
                  sent="#DDDD…D$ then #Ok$", expected=expected, got=got, info=info):
        passed += 1

    # Two frames inside one burst.
    board.write("$")
    time.sleep(SETTLE_S)
    mark = board.mark()
    board.write("#ab$#CD$")
    matches = board.wait_for_all(VALID_RE, 2, REPLY_TIMEOUT, mark)
    expected = ("two replies: Valid string: ab, lower-case: 2, upper-case: 0 "
                "then Valid string: CD, lower-case: 0, upper-case: 2")
    if len(matches) < 2:
        ok = False
        got = (" || ".join(m.group(0) for m in matches)
               if matches else "<timeout: fewer than two replies>")
        info = ("only %d of the 2 frames sent in one burst were answered - both frames "
                "arrive in the same DMA transfer and both have to be processed"
                % len(matches))
    else:
        got = " || ".join(m.group(0) for m in matches[:2])
        first_ok = (matches[0].group(1) == "ab" and int(matches[0].group(2)) == 2
                    and int(matches[0].group(3)) == 0)
        second_ok = (matches[1].group(1) == "CD" and int(matches[1].group(2)) == 0
                     and int(matches[1].group(3)) == 2)
        ok = first_ok and second_ok
        info = "" if ok else "the two frames were not reported correctly or in order"

    total += 1
    if report.add("string_parsing", "back_to_back", ok,
                  sent="#ab$#CD$", expected=expected, got=got, info=info):
        passed += 1

    report.data["cases_passed"] = passed
    report.data["cases_total"] = total
    report.data["string_parsing"] = "PASS" if passed == total else "FAIL"
    log("  string parsing: %d/%d cases passed" % (passed, total))
    return passed == total


# -- Phases -------------------------------------------------------------------

def phase_link(board, report):
    """Anything at all coming out of the board."""
    mark = board.mark()
    match = board.wait_for(re.compile(r"\S"), 8.0, mark)
    ok = match is not None
    report.data["link_alive"] = "PASS" if ok else "FAIL"
    report.add("link", "board_transmits", ok,
               sent=None,
               expected="any output on %s at %d Bd" % (board.port, board.baud),
               got=board.text_since(mark)[:120] if ok else "<silence for 8 s>",
               info="" if ok else (
                   "nothing was received. Either USART2/DMA is never enabled, the baud "
                   "rate does not match, or the firmware sends nothing at all."
               ))
    return ok


def phase_periodic(board, report, buffer_size):
    """The 0.5 Hz buffer state message, its format and its period."""
    mark = board.mark()
    matches = board.wait_for_all(BUFFER_RE, 3, 3 * REPORT_PERIOD_S + 4.0, mark)

    if not matches:
        raw = board.text_since(mark)
        report.add("periodic", "message_format", False,
                   sent=None,
                   expected="Buffer capacity: %d bytes, occupied memory: %d bytes, "
                            "load [in %]: %f%",
                   got=raw if raw.strip() else "<no output>",
                   info="no message matching the required format arrived within "
                        "%.0f s. Check the wording, and remember a literal percent "
                        "sign is written as '%%' in the format string."
                        % (3 * REPORT_PERIOD_S + 4.0))
        report.data["periodic_message"] = "FAIL"
        return False

    capacity = int(matches[0].group(1))
    occupied = int(matches[0].group(2))
    ok_format = report.add(
        "periodic", "message_format", True,
        sent=None, expected="the required buffer state format",
        got=matches[0].group(0), info="")

    ok_capacity = report.add(
        "periodic", "reported_capacity", capacity == buffer_size,
        sent=None,
        expected="capacity = %d bytes (DMA_USART2_BUFFER_SIZE from Inc/usart.h)"
                 % buffer_size,
        got=matches[0].group(0),
        info="" if capacity == buffer_size else (
            "the message reports a capacity of %d bytes, but bufferUSART2dma is %d "
            "bytes long - report the real size of the DMA Rx buffer"
            % (capacity, buffer_size)))

    ok_occupied = report.add(
        "periodic", "reported_occupancy", 0 <= occupied <= capacity,
        sent=None, expected="0 <= occupied memory <= capacity",
        got=matches[0].group(0),
        info="" if 0 <= occupied <= capacity else (
            "occupied memory (%d) is outside the buffer (%d bytes) - the value does "
            "not come from the DMA transfer counter" % (occupied, capacity)))

    # Period measured between the arrival of two further consecutive messages.
    ok_period = True
    m0 = board.mark()
    first = board.wait_for(BUFFER_RE, REPORT_PERIOD_S * 2 + 2.0, m0)
    t1 = time.time()
    m1 = board.mark()
    second = board.wait_for(BUFFER_RE, REPORT_PERIOD_S * 2 + 2.0, m1)
    t2 = time.time()

    if first is None or second is None:
        ok_period = report.add(
            "periodic", "transmission_period", False,
            sent=None,
            expected="a message every %.1f s (0.5 Hz)" % REPORT_PERIOD_S,
            got="only %d further message(s) within %.0f s"
                % (int(first is not None) + int(second is not None),
                   2 * (REPORT_PERIOD_S * 2 + 2.0)),
            info="the buffer state message does not arrive regularly at 0.5 Hz")
    else:
        period = t2 - t1
        report.data["periodic_period_s"] = round(period, 2)
        low = REPORT_PERIOD_S * (1 - REPORT_TOLERANCE)
        high = REPORT_PERIOD_S * (1 + REPORT_TOLERANCE)
        ok_period = low <= period <= high
        report.add("periodic", "transmission_period", ok_period,
                   sent=None,
                   expected="one message every %.1f s (0.5 Hz), tolerance %d %%"
                            % (REPORT_PERIOD_S, int(REPORT_TOLERANCE * 100)),
                   got="%.2f s between two consecutive messages" % period,
                   info="" if ok_period else (
                       "the buffer state message is sent every %.2f s instead of "
                       "%.1f s" % (period, REPORT_PERIOD_S)))

    ok = ok_format and ok_capacity and ok_occupied and ok_period
    report.data["periodic_message"] = "PASS" if ok else "FAIL"
    return ok


def phase_chunked(board, report):
    """A frame split over several bursts, as the DMA HT/TC/IDLE path must handle."""
    ok_all = True

    board.write("$")
    time.sleep(SETTLE_S)
    mark = board.mark()
    payload = "ChunkedTransferABCdef"          # 21 chars -> more than one burst
    board.write_chunked("#" + payload + "$", chunk=MAX_BURST, gap=0.08)
    lower, upper = letter_counts(payload)
    match = board.wait_for(VALID_RE, REPLY_TIMEOUT, mark)
    expected = "Valid string: %s, lower-case: %d, upper-case: %d" % (payload, lower, upper)
    if match is None:
        ok = False
        got = "<timeout: no reply within %.1f s>" % REPLY_TIMEOUT
        info = ("a set of characters delivered in several bursts of %d characters was "
                "never answered - the reception must survive being split across "
                "several DMA interrupts" % MAX_BURST)
    else:
        got = match.group(0)
        ok = (match.group(1) == payload and int(match.group(2)) == lower
              and int(match.group(3)) == upper)
        info = "" if ok else (
            "the set of characters was reassembled incorrectly from the separate bursts")
    ok_all &= report.add("chunked", "frame_split_into_bursts", ok,
                         sent="#" + payload + "$ (in %d-char bursts)" % MAX_BURST,
                         expected=expected, got=got, info=info)

    # Delimiters deliberately landing in different bursts.
    board.write("$")
    time.sleep(SETTLE_S)
    mark = board.mark()
    board.write("#split")
    time.sleep(0.25)
    board.write("Me$")
    match = board.wait_for(VALID_RE, REPLY_TIMEOUT, mark)
    expected = "Valid string: splitMe, lower-case: 6, upper-case: 1"
    if match is None:
        ok = False
        got = "<timeout: no reply within %.1f s>" % REPLY_TIMEOUT
        info = ("the '#' and the '$' arrived in two different transfers and the frame "
                "was lost - the parser state has to survive between DMA interrupts")
    else:
        got = match.group(0)
        ok = (match.group(1) == "splitMe" and int(match.group(2)) == 6
              and int(match.group(3)) == 1)
        info = "" if ok else "the two halves of the frame were not joined correctly"
    ok_all &= report.add("chunked", "delimiters_in_separate_bursts", ok,
                         sent="'#split' … 'Me$'", expected=expected, got=got, info=info)

    report.data["chunked_reception"] = "PASS" if ok_all else "FAIL"
    return ok_all


def phase_no_loss(board, report, buffer_size):
    """
    Enough traffic to run past the end of the Rx buffer several times. In normal
    mode this only works if the channel is re-armed and the read index reset.
    """
    frame_len = len("#L00abcDE$")
    count = max(20, int((2.5 * buffer_size) // frame_len) + 1)

    board.write("$")
    time.sleep(SETTLE_S)
    mark = board.mark()

    for i in range(count):
        board.write("#L%02dabcDE$" % (i % 100))
        time.sleep(0.03)          # keep every burst within the 20-character assumption

    matches = board.wait_for_all(VALID_RE, count, REPLY_TIMEOUT + count * 0.12, mark)
    received = len(matches)
    ok = received >= count

    total_bytes = count * frame_len
    expected = ("%d replies for %d frames (%d bytes, %.1f x the %d byte buffer)"
                % (count, count, total_bytes, total_bytes / float(buffer_size),
                   buffer_size))
    if ok:
        got = "%d replies" % received
        info = ""
    else:
        got = "%d of %d replies" % (received, count)
        info = ("%d sets of characters were lost. Once the DMA has written "
                "%d bytes the Rx buffer is full - in normal mode the channel stops "
                "and has to be disabled, given a fresh transfer length and enabled "
                "again in USART2_CheckDmaReception, with the read index reset."
                % (count - received, buffer_size))

    report.add("no_loss", "sustained_traffic", ok,
               sent="%d frames of the form #Lnnabcde$" % count,
               expected=expected, got=got, info=info)
    report.data["no_data_loss"] = "PASS" if ok else "FAIL"
    return ok


# -- Entry point --------------------------------------------------------------

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

    baud = read_baud()
    buffer_size = read_buffer_size()
    port = find_port()

    log("Assignment 4 hardware test - USART2 + DMA")
    log("  serial port : %s" % (port or "<none found>"))
    log("  baud rate   : %d Bd (read from Src/usart.c)" % baud)
    log("  buffer size : %d bytes (DMA_USART2_BUFFER_SIZE from Inc/usart.h)"
        % buffer_size)

    try:
        import serial  # noqa: F401
    except ImportError as exc:
        return fail_early(
            "pyserial is not available on the runner: %s. Install it with "
            "'python3 -m pip install pyserial'." % exc,
            port, baud, buffer_size)

    if port is None:
        return fail_early(
            "no serial port found. The Nucleo exposes USART2 through the ST-LINK as "
            "/dev/ttyACM*; check the USB cable, or set SERIAL_PORT explicitly.",
            port, baud, buffer_size)

    board = Board(port, baud)
    try:
        board.open()
    except Exception as exc:
        return fail_early(
            "cannot open %s at %d Bd: %s. If this is a permission error, the runner "
            "user has to be a member of the 'dialout' group." % (port, baud, exc),
            port, baud, buffer_size)

    report = Report(port, baud, buffer_size)

    try:
        # The board has just been reset by the flashing step.
        time.sleep(1.0)

        log("Phase 0 - the board is alive")
        if not phase_link(board, report):
            report.write()
            return 1

        log("Phase 1 - periodic buffer state message")
        phase_periodic(board, report, buffer_size)

        log("Phase 2 - input edge cases")
        run_frame_cases(board, report)

        log("Phase 3 - reception split across several bursts")
        phase_chunked(board, report)

        log("Phase 4 - sustained traffic, no data loss")
        phase_no_loss(board, report, buffer_size)

    except Exception as exc:                      # noqa: BLE001
        report.add("setup", "unexpected_error", False,
                   sent=None, expected="the test run to finish",
                   got=repr(exc),
                   info="the test script itself failed - this is a runner problem, "
                        "not necessarily a firmware fault")
    finally:
        board.close()

    ok = report.write()

    log("")
    log("Overall: %s" % ("PASS" if ok else "FAIL"))
    failed = [d for d in report.data["details"] if d["result"] == "FAIL"]
    if failed:
        log("Failed checks:")
        for detail in failed:
            log("  - %s/%s: %s" % (detail["phase"], detail["name"], detail["info"]))

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""
Static analysis tests for Assignment 4 - VRS cvicenie 4 (USART2 + DMA)
Target MCU: STM32F303K8Tx (Cortex-M4)

Checks performed WITHOUT compiling - pure text/regex analysis of:
  - Inc/usart.h         (DMA_USART2_BUFFER_SIZE)
  - Src/usart.c         (MX_USART2_UART_Init, USART2_CheckDmaReception)
  - Src/main.c          (proccesDmaData, callback registration, while(1) messages)

Peripheral map (STM32F303K8, RM0316):
  USART2 base : 0x40004400   ISR 0x…41C  ICR 0x…420  RDR 0x…424  TDR 0x…428
  DMA1   base : 0x40020000
  DMA1 ch6 (USART2_RX) base 0x4002006C -> CNDTR 0x40020070
  DMA1 ch7 (USART2_TX) base 0x40020080 -> CNDTR 0x40020084

Assignment 4 requirements:
  - DMA Rx on channel 6, periph->memory, memory increment, NORMAL mode (not circular)
  - DMA Tx on channel 7, memory->periph, normal mode
  - HT + TC interrupts on the Rx channel, IDLE interrupt on USART2
  - USART2_CheckDmaReception: tracks a read index, guards the end of the buffer,
    re-arms the channel, forwards every byte to the callback, never blocks
  - proccesDmaData: '#' starts a frame, '$' ends it, a second '#' RESTARTS the frame,
    the frame is discarded when '$' does not arrive within 35 characters (inclusive)
  - main(): registers the callback and emits the two required messages
"""

import re
from pathlib import Path

# -- Paths --------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
USART_H   = REPO_ROOT / "Inc" / "usart.h"
USART_C   = REPO_ROOT / "Src" / "usart.c"
MAIN_C    = REPO_ROOT / "Src" / "main.c"
IT_C      = REPO_ROOT / "Src" / "stm32f3xx_it.c"


# -- Helpers ------------------------------------------------------------------

def _read(path: Path) -> str:
    assert path.exists(), f"File not found: {path}"
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_comments(text: str) -> str:
    """Remove C-style block and line comments so regex hits real code."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def _strip_char_literals(text: str) -> str:
    """Remove 'x' character literals - '#' is also decimal 35 and would alias."""
    return re.sub(r"'(?:\\.|[^'\\])'", " ", text)


def _get_macro_value(source: str, macro_name: str):
    """Expansion text of a #define, or None when missing / empty."""
    clean = _strip_comments(source)
    m = re.search(rf"^\s*#\s*define\s+{re.escape(macro_name)}\s+(.*?)\s*$",
                  clean, re.MULTILINE)
    if not m:
        return None
    value = m.group(1).strip()
    return value if value else None


def _int_literal(text):
    """Parse 100, 100U, 0x64UL -> int, or None."""
    if text is None:
        return None
    m = re.match(r"^\(?\s*(0[xX][0-9a-fA-F]+|\d+)\s*[uUlL]*\s*\)?$", text.strip())
    return int(m.group(1), 0) if m else None


def _matching_brace_body(text: str, open_index: int):
    """Text between the '{' at open_index and its matching '}'."""
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_index + 1:i]
    return None


def _function_body(source: str, name: str):
    """
    Body of a C function definition with any return type and any parameter list.
    Returns None when the function is not defined in this source.
    """
    clean = _strip_comments(source)
    for m in re.finditer(rf"\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{", clean):
        body = _matching_brace_body(clean, m.end() - 1)
        if body is not None:
            return body
    return None


C_KEYWORDS = {"if", "else", "while", "for", "do", "switch", "return", "sizeof"}


def _top_level_functions(source: str) -> dict:
    """{name: body} of every function defined at file scope (brace depth 0)."""
    clean = _strip_comments(source)
    found = {}
    depth, pos = 0, 0
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{", clean):
        depth += clean.count("{", pos, m.start()) - clean.count("}", pos, m.start())
        pos = m.start()
        if depth == 0 and m.group(1) not in C_KEYWORDS:
            body = _matching_brace_body(clean, m.end() - 1)
            if body is not None:
                found.setdefault(m.group(1), body)
    return found


def _body_with_helpers(source: str, name: str):
    """
    Body of `name` followed by the bodies of the functions defined in the same file
    that it calls, transitively. Moving part of the work into a helper function is a
    legitimate design the assignment does not forbid.
    """
    functions = _top_level_functions(source)
    if name not in functions:
        return None
    seen, todo, parts = {name}, [name], []
    while todo:
        body = functions[todo.pop(0)]
        parts.append(body)
        for callee in functions:
            if callee not in seen and re.search(rf"\b{re.escape(callee)}\s*\(", body):
                seen.add(callee)
                todo.append(callee)
    return "\n".join(parts)


def _main_body(source: str):
    return _function_body(source, "main")


def _main_loop_body(source: str):
    """Body of the 'while (1)' loop inside main()."""
    clean = _strip_comments(source)
    m = re.search(r"while\s*\(\s*1\s*\)\s*\{", clean)
    if not m:
        return None
    return _matching_brace_body(clean, m.end() - 1)


def _mentions_any(text: str, names) -> bool:
    return any(re.search(rf"\b{re.escape(n)}\b", text) for n in names)


def _which(text: str, names):
    return [n for n in names if re.search(rf"\b{re.escape(n)}\b", text)]


def _call_args(text: str, func: str):
    """Every argument list passed to func(...) in text."""
    return re.findall(rf"\b{re.escape(func)}\s*\(([^;]*?)\)\s*;", text)


def _string_literals(text: str):
    """Every C string literal in text, with %% collapsed to a single %."""
    out = []
    for m in re.finditer(r'"((?:\\.|[^"\\])*)"', text):
        out.append(m.group(1).replace("%%", "%"))
    return out


def _joined_format_text(source: str) -> str:
    """All string literals joined, so a message split over several literals still matches."""
    return " ".join(_string_literals(_strip_comments(source)))


# -- Token alias groups -------------------------------------------------------
# Every check accepts the LL driver API or direct register access, because both
# are legitimate ways of configuring the peripheral.

RX_CHANNEL    = ("LL_DMA_CHANNEL_6", "DMA1_Channel6")
TX_CHANNEL    = ("LL_DMA_CHANNEL_7", "DMA1_Channel7")
MODE_NORMAL   = ("LL_DMA_MODE_NORMAL",)
MODE_CIRC     = ("LL_DMA_MODE_CIRCULAR", "DMA_CCR_CIRC")
DIR_P2M       = ("LL_DMA_DIRECTION_PERIPH_TO_MEMORY",)
DIR_M2P       = ("LL_DMA_DIRECTION_MEMORY_TO_PERIPH",)
MEM_INCREMENT = ("LL_DMA_MEMORY_INCREMENT", "DMA_CCR_MINC")
SET_LENGTH    = ("LL_DMA_SetDataLength", "CNDTR")
GET_LENGTH    = ("LL_DMA_GetDataLength", "CNDTR")
SET_ADDRESS   = ("LL_DMA_ConfigAddresses", "LL_DMA_SetPeriphAddress",
                 "LL_DMA_SetMemoryAddress", "CPAR", "CMAR")
IT_TC         = ("LL_DMA_EnableIT_TC", "DMA_CCR_TCIE")
IT_HT         = ("LL_DMA_EnableIT_HT", "DMA_CCR_HTIE")
IT_IDLE       = ("LL_USART_EnableIT_IDLE", "USART_CR1_IDLEIE")
DMAREQ_RX     = ("LL_USART_EnableDMAReq_RX", "USART_CR3_DMAR")
DMAREQ_TX     = ("LL_USART_EnableDMAReq_TX", "USART_CR3_DMAT")
USART_ENABLE  = ("LL_USART_Enable", "USART_CR1_UE")
CH_ENABLE     = ("LL_DMA_EnableChannel", "DMA_CCR_EN")
CH_DISABLE    = ("LL_DMA_DisableChannel",)

# Polling the receiver by hand - the whole point of the assignment is not to.
RDR_POLLING   = ("LL_USART_ReceiveData8", "LL_USART_ReceiveData9",
                 "LL_USART_IsActiveFlag_RXNE", "HAL_UART_Receive", "RDR")

# Blocking calls that must not appear in the DMA reception path.
DELAY_CALLS   = ("LL_mDelay", "HAL_Delay", "LL_Init1msTick", "delay_ms", "LL_uDelay")


def _usart_init_body():
    return _function_body(_read(USART_C), "MX_USART2_UART_Init")


def _check_dma_body():
    return _body_with_helpers(_read(USART_C), "USART2_CheckDmaReception")


def _process_body():
    return _body_with_helpers(_read(MAIN_C), "proccesDmaData")


# =============================================================================
# GROUP 0 - the files exist
# =============================================================================

def test_usart_h_exists():
    """Inc/usart.h must be present."""
    assert USART_H.exists(), f"Missing file: {USART_H}"


def test_usart_c_exists():
    """Src/usart.c must be present."""
    assert USART_C.exists(), f"Missing file: {USART_C}"


def test_main_c_exists():
    """Src/main.c must be present."""
    assert MAIN_C.exists(), f"Missing file: {MAIN_C}"


def test_buffer_size_macro_defined():
    """DMA_USART2_BUFFER_SIZE must stay defined - every other check reads it."""
    val = _int_literal(_get_macro_value(_read(USART_H), "DMA_USART2_BUFFER_SIZE"))
    assert val is not None, (
        "DMA_USART2_BUFFER_SIZE is missing from Inc/usart.h or is not a plain "
        "integer. It defines the size of 'bufferUSART2dma' and the capacity the "
        "periodic message has to report - do not delete or rename it."
    )
    assert val >= 32, (
        f"DMA_USART2_BUFFER_SIZE = {val}. The transmitter may send up to 20 "
        f"characters at once, so a buffer this small cannot work."
    )


# =============================================================================
# GROUP A - DMA and USART peripheral configuration (task 2)
# =============================================================================

def test_dma_rx_channel6_configured():
    """USART2 Rx uses DMA1 channel 6 - it must be configured in MX_USART2_UART_Init."""
    body = _usart_init_body()
    assert body is not None, "MX_USART2_UART_Init(void) is not defined in Src/usart.c."
    assert _mentions_any(body, RX_CHANNEL), (
        "MX_USART2_UART_Init does not configure DMA1 channel 6. USART2_RX is hard-wired "
        "to DMA1 channel 6 on the STM32F303 - configure it with LL_DMA_* calls using "
        "LL_DMA_CHANNEL_6 (see the '/* USART2_RX Init */' placeholder)."
    )


def test_dma_tx_channel7_configured():
    """USART2 Tx uses DMA1 channel 7 - USART2_PutBuffer already drives that channel."""
    body = _usart_init_body()
    if body is None:
        return
    assert _mentions_any(body, TX_CHANNEL), (
        "MX_USART2_UART_Init does not configure DMA1 channel 7. The provided "
        "USART2_PutBuffer() sends through LL_DMA_CHANNEL_7, so that channel must be "
        "set up in the '/* USART2_TX Init */' placeholder or nothing is ever sent."
    )


def test_dma_rx_mode_is_normal():
    """
    Task 3 states the Rx buffer is handled in NORMAL mode, not circular
    (the same is written in the comment above the placeholder in Src/usart.c).
    """
    source = _strip_comments(_read(USART_C))
    circular = _which(source, MODE_CIRC)
    assert not circular, (
        f"Src/usart.c configures the DMA in circular mode ({', '.join(circular)}). "
        f"Zadanie 4 requires the USART2 Rx buffer to be used in NORMAL mode - in "
        f"circular mode the DMA silently overwrites data that has not been read yet. "
        f"Use LL_DMA_MODE_NORMAL and re-arm the channel in USART2_CheckDmaReception."
    )
    assert _mentions_any(source, MODE_NORMAL), (
        "Src/usart.c never selects LL_DMA_MODE_NORMAL. Set the transfer mode of both "
        "DMA channels explicitly - the Rx channel must use normal mode."
    )


def test_dma_rx_direction_periph_to_memory():
    """Rx moves bytes from the USART peripheral into memory."""
    body = _usart_init_body()
    if body is None:
        return
    assert _mentions_any(body, DIR_P2M), (
        "The DMA Rx channel does not select LL_DMA_DIRECTION_PERIPH_TO_MEMORY. "
        "Reception copies from USART2->RDR into bufferUSART2dma, so the direction "
        "must be peripheral -> memory."
    )


def test_dma_tx_direction_memory_to_periph():
    """Tx moves bytes from memory into the USART peripheral."""
    body = _usart_init_body()
    if body is None:
        return
    assert _mentions_any(body, DIR_M2P), (
        "The DMA Tx channel does not select LL_DMA_DIRECTION_MEMORY_TO_PERIPH. "
        "Transmission copies from your buffer into USART2->TDR."
    )


def test_dma_rx_memory_increment():
    """Without memory increment every received byte lands on the same address."""
    body = _usart_init_body()
    if body is None:
        return
    assert _mentions_any(body, MEM_INCREMENT), (
        "The DMA configuration never enables the memory increment mode "
        "(LL_DMA_MEMORY_INCREMENT / DMA_CCR_MINC). Without it every received byte is "
        "written to the very first address of bufferUSART2dma and the previous one is "
        "lost."
    )


def test_dma_rx_addresses_use_buffer():
    """The Rx channel must point at bufferUSART2dma and at the USART2 data register."""
    body = _usart_init_body()
    if body is None:
        return
    assert _mentions_any(body, SET_ADDRESS), (
        "The DMA channels never get their addresses (LL_DMA_ConfigAddresses / "
        "LL_DMA_SetPeriphAddress + LL_DMA_SetMemoryAddress). The DMA has no idea where "
        "to read from or write to."
    )
    assert re.search(r"\bbufferUSART2dma\b", body), (
        "MX_USART2_UART_Init never references 'bufferUSART2dma'. That array is the "
        "memory the DMA must fill on reception - pass its address to the Rx channel."
    )


def test_dma_rx_length_is_buffer_size():
    """The Rx transfer length must be the full buffer, i.e. DMA_USART2_BUFFER_SIZE."""
    body = _usart_init_body()
    if body is None:
        return
    assert _mentions_any(body, SET_LENGTH), (
        "The DMA Rx channel never gets a transfer length (LL_DMA_SetDataLength). "
        "In normal mode the channel stops after exactly that many bytes, so the length "
        "has to be programmed."
    )
    assert re.search(r"\bDMA_USART2_BUFFER_SIZE\b", body), (
        "The DMA transfer length is not derived from DMA_USART2_BUFFER_SIZE. Use the "
        "macro instead of a hard-coded number so the buffer and the length can never "
        "disagree."
    )


def test_dma_rx_ht_and_tc_interrupts_enabled():
    """DMA1_Channel6_IRQHandler reacts to HT6 and TC6 - both must be enabled."""
    body = _usart_init_body()
    if body is None:
        return
    missing = []
    if not _mentions_any(body, IT_TC):
        missing.append("transfer complete (LL_DMA_EnableIT_TC)")
    if not _mentions_any(body, IT_HT):
        missing.append("half transfer (LL_DMA_EnableIT_HT)")
    assert not missing, (
        f"The DMA Rx channel does not enable: {', '.join(missing)}. "
        f"The provided DMA1_Channel6_IRQHandler in Src/stm32f3xx_it.c tests both the "
        f"TC6 and the HT6 flag, so both interrupts have to be enabled or the handler "
        f"is never called."
    )


def test_usart_idle_interrupt_enabled():
    """The IDLE interrupt is what ends a burst shorter than the buffer."""
    body = _usart_init_body()
    if body is None:
        return
    assert _mentions_any(body, IT_IDLE), (
        "USART2 never enables the IDLE line detection interrupt "
        "(LL_USART_EnableIT_IDLE). The provided USART2_IRQHandler reacts to the IDLE "
        "flag - it is the only thing that reports a burst that did not fill the buffer, "
        "so without it short messages are never processed."
    )


def test_usart_dma_requests_enabled():
    """The USART has to actually ask the DMA for service, in both directions."""
    body = _usart_init_body()
    if body is None:
        return
    missing = []
    if not _mentions_any(body, DMAREQ_RX):
        missing.append("Rx (LL_USART_EnableDMAReq_RX)")
    if not _mentions_any(body, DMAREQ_TX):
        missing.append("Tx (LL_USART_EnableDMAReq_TX)")
    assert not missing, (
        f"USART2 does not enable the DMA request for: {', '.join(missing)}. "
        f"Configuring the DMA channel is not enough - the USART must be told to raise a "
        f"DMA request (CR3 DMAR/DMAT bits)."
    )


def test_usart_and_rx_channel_enabled():
    """Nothing runs until USART2 and the Rx DMA channel are switched on."""
    body = _usart_init_body()
    if body is None:
        return
    assert _mentions_any(body, USART_ENABLE), (
        "USART2 is never enabled. Finish MX_USART2_UART_Init with "
        "LL_USART_Enable(USART2) (the '/* Enable USART2 peripheral and interrupts*/' "
        "placeholder)."
    )
    assert _mentions_any(body, CH_ENABLE), (
        "The DMA Rx channel is never enabled (LL_DMA_EnableChannel). The channel has to "
        "be running before the first byte arrives."
    )


def test_main_loop_does_not_poll_the_receiver():
    """
    The data path is USART -> DMA -> interrupt -> callback. Reading RDR or polling
    RXNE in the main loop is the polling solution the assignment replaces.
    """
    loop = _main_loop_body(_read(MAIN_C))
    if loop is None:
        return
    polled = _which(_strip_comments(loop), RDR_POLLING)
    assert not polled, (
        f"The 'while (1)' loop in main() reads the receiver directly "
        f"({', '.join(polled)}). Zadanie 4 requires reception through DMA with the "
        f"HT/TC/IDLE interrupts - the main loop only sends the two required messages."
    )


def test_main_does_not_call_check_dma_reception():
    """USART2_CheckDmaReception is called by the ISRs, not by the main loop."""
    loop = _main_loop_body(_read(MAIN_C))
    if loop is None:
        return
    assert not re.search(r"\bUSART2_CheckDmaReception\s*\(", _strip_comments(loop)), (
        "main()'s while(1) loop calls USART2_CheckDmaReception() itself. That is the "
        "polling variant described in the README. In this assignment the function is "
        "invoked from DMA1_Channel6_IRQHandler and USART2_IRQHandler (already written "
        "in Src/stm32f3xx_it.c)."
    )


# =============================================================================
# GROUP B - USART2_CheckDmaReception (task 3)
# =============================================================================

def test_check_dma_reception_is_not_a_stub():
    """The function must actually be implemented."""
    body = _check_dma_body()
    assert body is not None, (
        "USART2_CheckDmaReception(void) is not defined in Src/usart.c."
    )
    assert len(body.strip()) > 20, (
        "USART2_CheckDmaReception is still the empty template stub. It has to work out "
        "how many new bytes the DMA has written and pass each of them to the callback."
    )


def test_check_dma_reception_reads_remaining_length():
    """How many bytes arrived is derived from the channel's CNDTR."""
    body = _check_dma_body()
    if body is None:
        return
    assert _mentions_any(body, GET_LENGTH), (
        "USART2_CheckDmaReception never reads the remaining transfer length "
        "(LL_DMA_GetDataLength / CNDTR). That counter is the only way to know how far "
        "the DMA has got - the number of received bytes is "
        "DMA_USART2_BUFFER_SIZE - LL_DMA_GetDataLength(...)."
    )


def test_check_dma_reception_keeps_a_read_index():
    """State has to survive between calls, otherwise every call re-reads the buffer."""
    source = _strip_comments(_read(USART_C))
    body = _check_dma_body()
    if body is None:
        return
    has_static_local = re.search(r"\bstatic\b", body) is not None
    # A file-scope variable declared outside every function also counts.
    globals_declared = set(
        re.findall(r"^\s*(?:static\s+)?(?:volatile\s+)?u?int\d*_t\s+(\w+)\s*(?:=|;)",
                   source, re.MULTILINE)
    )
    assigned = set(re.findall(r"\b([A-Za-z_]\w*)\s*(?:=[^=]|\+\+|--|\+=|-=)", body))
    has_global_state = bool(globals_declared & assigned)
    assert has_static_local or has_global_state, (
        "USART2_CheckDmaReception keeps no state between calls. It is called again on "
        "every HT, TC and IDLE interrupt, so it must remember the position it has "
        "already read up to - use a 'static' variable inside the function or a global "
        "in Src/usart.c."
    )


def test_check_dma_reception_calls_the_callback():
    """Every received byte is forwarded to the registered callback."""
    body = _check_dma_body()
    if body is None:
        return
    assert re.search(r"\bUSART2_ProcessData\s*\(", body), (
        "USART2_CheckDmaReception never calls USART2_ProcessData(...). That function "
        "pointer is the callback registered from main() with USART2_RegisterCallback - "
        "it is how the received bytes reach proccesDmaData()."
    )


def test_check_dma_reception_guards_the_buffer_end():
    """
    Task 3: check how full the Rx buffer is and prevent an overflow / loss of data.
    """
    body = _check_dma_body()
    if body is None:
        return
    assert re.search(r"\bDMA_USART2_BUFFER_SIZE\b", body), (
        "USART2_CheckDmaReception never compares anything against "
        "DMA_USART2_BUFFER_SIZE. Task 3 requires you to watch how full the Rx buffer is "
        "and reset the DMA before the next reception can overflow it."
    )
    assert re.search(r"[<>]=?|==|!=", body), (
        "USART2_CheckDmaReception contains no comparison at all, so it cannot be "
        "detecting that the buffer is about to overflow."
    )


def test_check_dma_reception_rearms_the_channel():
    """
    In normal mode the channel stops when CNDTR reaches 0 and the length can only be
    reprogrammed while the channel is disabled.
    """
    body = _check_dma_body()
    if body is None:
        return
    missing = []
    if not _mentions_any(body, CH_DISABLE):
        missing.append("LL_DMA_DisableChannel")
    if not _mentions_any(body, CH_ENABLE):
        missing.append("LL_DMA_EnableChannel")
    if not _mentions_any(body, SET_LENGTH):
        missing.append("LL_DMA_SetDataLength")
    assert not missing, (
        f"USART2_CheckDmaReception never re-arms the DMA Rx channel (missing: "
        f"{', '.join(missing)}). The buffer is used in NORMAL mode, so once the read "
        f"pointer reaches the end the channel has to be disabled, given a fresh "
        f"transfer length and enabled again - otherwise reception stops for good."
    )


def test_check_dma_reception_does_not_block():
    """It runs in interrupt context - it must not wait for anything."""
    body = _check_dma_body()
    if body is None:
        return
    blocking = _which(body, DELAY_CALLS)
    assert not blocking, (
        f"USART2_CheckDmaReception calls a blocking delay ({', '.join(blocking)}). "
        f"It runs inside the DMA and USART interrupt handlers - blocking there stalls "
        f"reception and loses data."
    )
    assert not re.search(r"while\s*\(\s*1\s*\)", body), (
        "USART2_CheckDmaReception contains an endless 'while (1)' loop. The function is "
        "called from interrupt context and has to return promptly."
    )


# =============================================================================
# GROUP C - proccesDmaData, frame detection and letter counting (task 5)
# =============================================================================

def test_process_dma_data_is_not_a_stub():
    """The processing function must be implemented."""
    body = _process_body()
    assert body is not None, (
        "proccesDmaData(uint8_t sign) is not defined in Src/main.c. Keep the name "
        "exactly as the template spells it."
    )
    assert len(body.strip()) > 20, (
        "proccesDmaData is still the empty template stub. It receives the characters "
        "one by one and has to detect a '#'…'$' frame and count its letters."
    )


def test_process_dma_data_uses_frame_delimiters():
    """'#' starts a frame, '$' ends it."""
    body = _process_body()
    if body is None:
        return
    text = _strip_comments(body)
    has_start = "'#'" in text or re.search(r"\b0[xX]23\b", text)
    has_end = "'$'" in text or re.search(r"\b0[xX]24\b", text)
    missing = []
    if not has_start:
        missing.append("start character '#'")
    if not has_end:
        missing.append("end character '$'")
    assert not missing, (
        f"proccesDmaData never tests for the {' and the '.join(missing)}. A set of "
        f"characters is only evaluated when it starts with '#' and ends with '$' - "
        f"everything received before a '#' is ignored."
    )


def test_process_dma_data_keeps_state_between_calls():
    """One call handles one character, so the frame has to be assembled in state."""
    body = _process_body()
    source = _strip_comments(_read(MAIN_C))
    if body is None:
        return
    has_static_local = re.search(r"\bstatic\b", body) is not None
    globals_declared = set(
        re.findall(r"^\s*(?:static\s+)?(?:volatile\s+)?(?:u?int\d*_t|char|letter_count_)"
                   r"\s+\*?\s*(\w+)\s*(?:\[|=|;)", source, re.MULTILINE)
    )
    assigned = set(
        re.findall(r"\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:=[^=]|\+\+|--|\+=)", body)
    )
    assert has_static_local or (globals_declared & assigned), (
        "proccesDmaData keeps no state between calls. It is invoked once per received "
        "character, so the collected characters, the 'frame is open' flag and the "
        "counters must live in 'static' variables or in globals."
    )


def test_letter_count_global_is_defined():
    """The result belongs in a global of the provided type letter_count_."""
    source = _strip_comments(_read(MAIN_C))
    assert re.search(r"\bletter_count_\b", source), (
        "Src/main.c never uses the 'letter_count_' type. The comment above "
        "proccesDmaData says the result has to be stored in a global variable of that "
        "type (it is declared in Inc/main.h)."
    )


def test_process_dma_data_classifies_letter_case():
    """Counting small and capital letters needs an actual case test."""
    body = _process_body()
    if body is None:
        return
    text = _strip_comments(body)
    range_style = ("'a'" in text and "'z'" in text) or ("'A'" in text and "'Z'" in text)
    ctype_style = _mentions_any(text, ("islower", "isupper", "isalpha"))
    assert range_style or ctype_style, (
        "proccesDmaData never distinguishes small from capital letters. Compare the "
        "character against the 'a'..'z' and 'A'..'Z' ranges (or use islower/isupper) - "
        "digits and punctuation count as neither."
    )


def test_frame_timeout_is_35_characters():
    """
    A frame that gets no '$' within 35 characters is thrown away. Depending on how the
    characters are counted the limit is written as 34, 35 or 36 - the hardware test
    checks the exact boundary.
    """
    source = _strip_char_literals(_strip_comments(_read(MAIN_C)))
    assert re.search(r"(?<![\w.])3[456][uUlL]*(?![\w.])", source), (
        "The number 35 does not appear in Src/main.c. Task 5: if the closing '$' does "
        "not arrive within 35 characters of the '#', the collected data is discarded "
        "and the function waits for a new start character."
    )


def test_callback_is_registered_in_main():
    """proccesDmaData only ever runs if it is handed to the USART driver."""
    body = _main_body(_read(MAIN_C))
    assert body is not None, "int main(void) is not defined in Src/main.c."
    args = " ".join(_call_args(body, "USART2_RegisterCallback"))
    assert args, (
        "main() never calls USART2_RegisterCallback(...). Without registering the "
        "callback, USART2_CheckDmaReception has nowhere to send the received bytes and "
        "proccesDmaData is never executed."
    )
    assert re.search(r"\bproccesDmaData\b", args), (
        f"USART2_RegisterCallback is called with '{args.strip()}' instead of "
        f"proccesDmaData. The callback must be the data-processing function."
    )


def test_valid_string_message_format():
    """Message format - 'Valid string: %s, lower-case: %d, upper-case: %d'."""
    text = _joined_format_text(_read(MAIN_C))
    pattern = (r"Valid\s+string:\s*%[-+ #0-9.]*s\s*,\s*"
               r"lower-case:\s*%[-+ #0-9.]*(?:h?[diu]|l[diu])\s*,\s*"
               r"upper-case:\s*%[-+ #0-9.]*(?:h?[diu]|l[diu])")
    assert re.search(pattern, text, re.IGNORECASE), (
        "The message announcing a valid string does not match the required format.\n"
        "  expected: \"Valid string: %s, lower-case: %d, upper-case: %d\"\n"
        "  example : Valid string: Platn15uborZnakov, lower-case: 13, upper-case: 2\n"
        "The exact wording is given in the comment inside the while loop of main() - "
        "the terminal output is what gets graded, so it has to match."
    )


def test_valid_string_is_sent_with_putbuffer():
    """Sending goes through the provided DMA transmit helper."""
    source = _strip_comments(_read(MAIN_C))
    assert re.search(r"\bUSART2_PutBuffer\s*\(", source), (
        "Src/main.c never calls USART2_PutBuffer(...). That is the provided function "
        "that hands a buffer to DMA1 channel 7 - both required messages have to be sent "
        "with it so the transmission also uses the DMA."
    )


# =============================================================================
# GROUP D - periodic DMA Rx buffer state message (task 6)
# =============================================================================

def test_buffer_state_message_format():
    """
    Message format -
    'Buffer capacity: %d bytes, occupied memory: %d bytes, load [in %]: %f%'

    What is graded is the text on the terminal, so the load may also be printed as an
    integer part and a fraction ("%u.%u%%") instead of with a float conversion.
    """
    text = _joined_format_text(_read(MAIN_C))
    num = r"%[-+ #0-9.]*(?:h?[diu]|l[diu])"
    load = rf"(?:%[-+ #0-9.]*[fgeFGE]|{num}\s*[.,]\s*{num})"
    pattern = (rf"Buffer\s+capacity:\s*{num}\s*bytes\s*,\s*"
               rf"occupied\s+memory:\s*{num}\s*bytes\s*,\s*"
               rf"load\s*\[\s*in\s*%\s*\]\s*:\s*{load}")
    assert re.search(pattern, text, re.IGNORECASE), (
        "The periodic buffer-state message does not match the required format.\n"
        "  expected: \"Buffer capacity: %d bytes, occupied memory: %d bytes, "
        "load [in %]: %f%\"\n"
        "  example : Buffer capacity: 256 bytes, occupied memory: 231 bytes, "
        "load [in %]: 23.1%\n"
        "The format is given in the comment inside the while loop of main(). Remember "
        "that a literal percent sign has to be written as '%%' in the format string."
    )


def test_buffer_state_uses_the_real_dma_state():
    """The reported occupancy must come from the DMA, not be invented."""
    source = _strip_comments(_read(MAIN_C))
    uses_size = re.search(r"\bDMA_USART2_BUFFER_SIZE\b", source) is not None
    uses_len = _mentions_any(source, GET_LENGTH)
    assert uses_size or uses_len, (
        "Src/main.c computes the buffer state without ever reading "
        "DMA_USART2_BUFFER_SIZE or the remaining DMA transfer length "
        "(LL_DMA_GetDataLength). The reported capacity and occupancy have to describe "
        "the real state of the DMA Rx buffer."
    )


def test_periodic_transmission_is_every_two_seconds():
    """
    Transmission frequency - 0.5 Hz, i.e. one message every 2000 ms. The hardware test
    measures the real period; this only looks for a plausible 2 s time base.
    """
    source = _strip_char_literals(_strip_comments(_read(MAIN_C)))
    # 2000 / 500 ms, or 1999 / 499 as a timer auto-reload value
    milliseconds = re.search(r"(?<![\w.])(2000|1999|500|499)[uUlL]*(?![\w.])", source)
    # a cycle counter (DWT->CYCCNT, SysTick) scaled from the core clock
    core_clock = re.search(r"\bSystemCoreClock\b\s*\)?\s*[*/]|[*/]\s*\(?\s*SystemCoreClock\b",
                           source)
    # 2 s worth of cycles at 8 / 64 / 72 MHz
    cycles = re.search(r"(?<![\w.])(16000000|128000000|144000000)[uUlL]*(?![\w.])", source)
    assert milliseconds or core_clock or cycles, (
        "Src/main.c contains no recognisable 2 second time base (2000 ms, 500 ms, or a "
        "cycle count derived from SystemCoreClock). The buffer-state message has to be "
        "sent every 2 seconds - for example count 2000 SysTick milliseconds or call "
        "LL_mDelay(2000)."
    )

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from typing import Any

from powershell_backends import PowerShellBackend, create_backend


KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11

ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
ENABLE_WINDOW_INPUT = 0x0008
ENABLE_MOUSE_INPUT = 0x0010
ENABLE_INSERT_MODE = 0x0020
ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200

ENABLE_PROCESSED_OUTPUT = 0x0001
ENABLE_WRAP_AT_EOL_OUTPUT = 0x0002
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

KEY_EVENT = 0x0001
MOUSE_EVENT = 0x0002
WINDOW_BUFFER_SIZE_EVENT = 0x0004

FROM_LEFT_1ST_BUTTON_PRESSED = 0x0001

SHIFT_PRESSED = 0x0010

VK_BACK = 0x08
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_UP = 0x26
VK_DOWN = 0x28
VK_PRIOR = 0x21  # PageUp
VK_NEXT = 0x22  # PageDown
VK_END = 0x23
VK_HOME = 0x24
VK_OEM_PLUS = 0xBB
VK_OEM_MINUS = 0xBD


class COORD(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [
        ("Left", wintypes.SHORT),
        ("Top", wintypes.SHORT),
        ("Right", wintypes.SHORT),
        ("Bottom", wintypes.SHORT),
    ]


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", COORD),
        ("dwCursorPosition", COORD),
        ("wAttributes", wintypes.WORD),
        ("srWindow", SMALL_RECT),
        ("dwMaximumWindowSize", COORD),
    ]


class MOUSE_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("dwMousePosition", COORD),
        ("dwButtonState", wintypes.DWORD),
        ("dwControlKeyState", wintypes.DWORD),
        ("dwEventFlags", wintypes.DWORD),
    ]


MOUSE_WHEELED = 0x0004


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("uChar", wintypes.WCHAR),
        ("dwControlKeyState", wintypes.DWORD),
    ]


class WINDOW_BUFFER_SIZE_RECORD(ctypes.Structure):
    _fields_ = [("dwSize", COORD)]


class EVENT_UNION(ctypes.Union):
    _fields_ = [
        ("KeyEvent", KEY_EVENT_RECORD),
        ("MouseEvent", MOUSE_EVENT_RECORD),
        ("WindowBufferSizeEvent", WINDOW_BUFFER_SIZE_RECORD),
    ]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", wintypes.WORD), ("Event", EVENT_UNION)]


# WinAPI prototypes (important: avoids garbage chars on FillConsoleOutputCharacterW)
KERNEL32.GetStdHandle.argtypes = [wintypes.DWORD]
KERNEL32.GetStdHandle.restype = wintypes.HANDLE

KERNEL32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
KERNEL32.GetConsoleMode.restype = wintypes.BOOL

KERNEL32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
KERNEL32.SetConsoleMode.restype = wintypes.BOOL

KERNEL32.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO)]
KERNEL32.GetConsoleScreenBufferInfo.restype = wintypes.BOOL

KERNEL32.ReadConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(INPUT_RECORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
KERNEL32.ReadConsoleInputW.restype = wintypes.BOOL

KERNEL32.GetNumberOfConsoleInputEvents.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
KERNEL32.GetNumberOfConsoleInputEvents.restype = wintypes.BOOL

KERNEL32.SetConsoleCursorPosition.argtypes = [wintypes.HANDLE, COORD]
KERNEL32.SetConsoleCursorPosition.restype = wintypes.BOOL

KERNEL32.WriteConsoleOutputCharacterW.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    COORD,
    ctypes.POINTER(wintypes.DWORD),
]
KERNEL32.WriteConsoleOutputCharacterW.restype = wintypes.BOOL

KERNEL32.FillConsoleOutputCharacterW.argtypes = [
    wintypes.HANDLE,
    wintypes.WCHAR,
    wintypes.DWORD,
    COORD,
    ctypes.POINTER(wintypes.DWORD),
]
KERNEL32.FillConsoleOutputCharacterW.restype = wintypes.BOOL

KERNEL32.WriteConsoleOutputAttribute.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.WORD),
    wintypes.DWORD,
    COORD,
    ctypes.POINTER(wintypes.DWORD),
]
KERNEL32.WriteConsoleOutputAttribute.restype = wintypes.BOOL

KERNEL32.FillConsoleOutputAttribute.argtypes = [
    wintypes.HANDLE,
    wintypes.WORD,
    wintypes.DWORD,
    COORD,
    ctypes.POINTER(wintypes.DWORD),
]
KERNEL32.FillConsoleOutputAttribute.restype = wintypes.BOOL


def _check(ok: bool) -> None:
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def get_handle(which: int) -> wintypes.HANDLE:
    h = KERNEL32.GetStdHandle(which)
    if h in (0, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    return h


def get_console_info(h_out) -> CONSOLE_SCREEN_BUFFER_INFO:
    info = CONSOLE_SCREEN_BUFFER_INFO()
    _check(KERNEL32.GetConsoleScreenBufferInfo(h_out, ctypes.byref(info)))
    return info


def set_console_mode(h, mode: int) -> None:
    _check(KERNEL32.SetConsoleMode(h, mode))


def get_console_mode(h) -> int:
    mode = wintypes.DWORD()
    _check(KERNEL32.GetConsoleMode(h, ctypes.byref(mode)))
    return int(mode.value)


def enable_vt_output(h_out) -> None:
    mode = get_console_mode(h_out)
    mode |= ENABLE_VIRTUAL_TERMINAL_PROCESSING | ENABLE_PROCESSED_OUTPUT | ENABLE_WRAP_AT_EOL_OUTPUT
    set_console_mode(h_out, mode)


def enable_mouse_input(h_in) -> None:
    mode = get_console_mode(h_in)
    # Disable Quick Edit (иначе мышь выделяет текст и события клика "залипают")
    mode &= ~ENABLE_QUICK_EDIT_MODE
    mode |= ENABLE_EXTENDED_FLAGS | ENABLE_MOUSE_INPUT | ENABLE_WINDOW_INPUT
    set_console_mode(h_in, mode)


def read_console_input(h_in, max_events: int = 1) -> list[INPUT_RECORD]:
    buf = (INPUT_RECORD * max_events)()
    read = wintypes.DWORD()
    _check(KERNEL32.ReadConsoleInputW(h_in, buf, max_events, ctypes.byref(read)))
    return list(buf[: read.value])


def get_pending_input_events(h_in) -> int:
    n = wintypes.DWORD()
    _check(KERNEL32.GetNumberOfConsoleInputEvents(h_in, ctypes.byref(n)))
    return int(n.value)


def write(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


def cursor_move(x: int, y: int) -> str:
    # 1-based in ANSI
    return f"\x1b[{y+1};{x+1}H"


def clear_line() -> str:
    return "\x1b[2K"


def hide_cursor() -> str:
    return "\x1b[?25l"


def show_cursor() -> str:
    return "\x1b[?25h"


def reverse_video(on: bool) -> str:
    return "\x1b[7m" if on else "\x1b[27m"


def reset_style() -> str:
    return "\x1b[0m"


def clear_screen() -> str:
    return "\x1b[2J\x1b[H"


def build_menu(items: list[str], active_idx: int) -> tuple[str, list[tuple[int, int]]]:
    """
    Returns (rendered_string, hit_boxes).
    hit_boxes is list of (start_x_inclusive, end_x_exclusive) for each item.
    """
    parts: list[str] = []
    hit: list[tuple[int, int]] = []
    x = 0

    for i, label in enumerate(items):
        pad = f" {label} "
        start = x
        end = x + len(pad)
        hit.append((start, end))
        if i == active_idx:
            parts.append(reverse_video(True) + pad + reverse_video(False))
        else:
            parts.append(pad)
        x = end
        if i != len(items) - 1:
            parts.append(" ")
            x += 1

    return "".join(parts), hit


class WUakeSession:
    def __init__(self, name: str, backend_config: dict[str, Any]):
        self.name = name
        self.backend: PowerShellBackend = create_backend(backend_config)
        self.transcript: list[str] = []
        self.cmd_history: list[str] = []
        self.history_idx: int | None = None
        self.scroll_offset = 0  # 0 = bottom (latest)

    def start(self) -> None:
        self.backend.start()

    def stop(self) -> None:
        self.backend.stop()

    def run_command(self, cmd: str) -> list[str]:
        self.start()

        self.cmd_history.append(cmd)
        self.history_idx = None
        self.scroll_offset = 0

        self.transcript.append(f"ps> {cmd}")
        try:
            out_lines = self.backend.run_command(cmd)
        except Exception as exc:
            out_lines = [f"[backend error] {exc}"]

        if out_lines:
            self.transcript.extend(out_lines)
        return out_lines


def load_sessions_config(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("sessions", [])
        names = []
        for x in raw:
            if isinstance(x, dict) and isinstance(x.get("name"), str) and x["name"].strip():
                names.append(x["name"].strip())
        return names
    except Exception:
        return []


def save_sessions_config(path: str, names: list[str]) -> None:
    data = {"sessions": [{"name": n} for n in names]}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def ensure_sessions_file(path: str) -> None:
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_sessions_config(path, ["shell"])


def load_runner_settings(path: str) -> dict:
    defaults = {
        "keybindings": {
            "add_session": {"vk": VK_OEM_PLUS, "shift": True},
            "delete_session": {"vk": VK_OEM_MINUS, "shift": True},
        },
        "backend": {
            "mode": "subprocess",
            "powershell_exe": os.environ.get("WUAKE_POWERSHELL", "powershell.exe"),
            "ssh": {
                "host": "",
                "user": "",
                "port": 22,
                "remote_shell": "pwsh",
                "ssh_binary": "ssh",
            },
        },
    }
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(defaults, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return defaults
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return defaults
        kb = data.get("keybindings")
        if not isinstance(kb, dict):
            data["keybindings"] = defaults["keybindings"]
            return data
        for k in ("add_session", "delete_session"):
            if not isinstance(kb.get(k), dict):
                kb[k] = defaults["keybindings"][k]
            kb[k]["vk"] = int(kb[k].get("vk", defaults["keybindings"][k]["vk"]))
            kb[k]["shift"] = bool(kb[k].get("shift", defaults["keybindings"][k]["shift"]))
        backend = data.get("backend")
        if not isinstance(backend, dict):
            data["backend"] = defaults["backend"]
            backend = data["backend"]
        mode = str(backend.get("mode", defaults["backend"]["mode"])).strip().lower()
        if mode not in {"subprocess", "dotnet", "ssh"}:
            mode = defaults["backend"]["mode"]
        backend["mode"] = mode
        backend["powershell_exe"] = str(
            backend.get("powershell_exe", defaults["backend"]["powershell_exe"])
        ).strip() or defaults["backend"]["powershell_exe"]
        ssh = backend.get("ssh")
        if not isinstance(ssh, dict):
            ssh = {}
            backend["ssh"] = ssh
        ssh_defaults = defaults["backend"]["ssh"]
        ssh["host"] = str(ssh.get("host", ssh_defaults["host"])).strip()
        ssh["user"] = str(ssh.get("user", ssh_defaults["user"])).strip()
        try:
            ssh["port"] = int(ssh.get("port", ssh_defaults["port"]))
        except Exception:
            ssh["port"] = int(ssh_defaults["port"])
        ssh["remote_shell"] = str(ssh.get("remote_shell", ssh_defaults["remote_shell"])).strip() or ssh_defaults["remote_shell"]
        ssh["ssh_binary"] = str(ssh.get("ssh_binary", ssh_defaults["ssh_binary"])).strip() or ssh_defaults["ssh_binary"]
        return data
    except Exception:
        return defaults


def next_session_name(existing: list[str], base: str = "shell") -> str:
    used = set(existing)
    if base not in used:
        return base
    i = 2
    while True:
        name = f"{base}-{i}"
        if name not in used:
            return name
        i += 1


def _attr_reverse(attr: int) -> int:
    fg = attr & 0x0F
    bg = (attr & 0xF0) >> 4
    return (fg << 4) | bg


def win_set_cursor(h_out, x: int, y: int) -> None:
    coord = COORD(x, y)
    _check(KERNEL32.SetConsoleCursorPosition(h_out, coord))


def win_write_at(h_out, x: int, y: int, text: str, attr: int | None = None) -> None:
    if text == "":
        return
    written = wintypes.DWORD()
    _check(KERNEL32.WriteConsoleOutputCharacterW(h_out, text, len(text), COORD(x, y), ctypes.byref(written)))
    if attr is not None:
        attrs = (wintypes.WORD * len(text))()
        for i in range(len(text)):
            attrs[i] = wintypes.WORD(attr)
        _check(KERNEL32.WriteConsoleOutputAttribute(h_out, attrs, len(text), COORD(x, y), ctypes.byref(written)))


def win_fill_line(h_out, x: int, y: int, width: int, ch: str = " ", attr: int | None = None) -> None:
    if width <= 0:
        return
    if not ch:
        ch = " "
    written = wintypes.DWORD()
    _check(KERNEL32.FillConsoleOutputCharacterW(h_out, wintypes.WCHAR(ch[0]), width, COORD(x, y), ctypes.byref(written)))
    if attr is not None:
        _check(KERNEL32.FillConsoleOutputAttribute(h_out, wintypes.WORD(attr), width, COORD(x, y), ctypes.byref(written)))


def main() -> int:
    if os.name != "nt":
        print("runner.py рассчитан на Windows-консоль.", file=sys.stderr)
        return 1

    h_in = get_handle(STD_INPUT_HANDLE)
    h_out = get_handle(STD_OUTPUT_HANDLE)

    old_in_mode = get_console_mode(h_in)
    old_out_mode = get_console_mode(h_out)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(base_dir, "sessions.json")
    ensure_sessions_file(cfg_path)
    items = load_sessions_config(cfg_path) or ["shell"]
    settings_path = os.path.join(base_dir, "runner_settings.json")
    settings = load_runner_settings(settings_path)
    kb = settings["keybindings"]
    active = 0
    hit_boxes: list[tuple[int, int]] = []
    last_window_rect: tuple[int, int, int, int] | None = None
    input_buf = ""
    scroll_mode = False

    backend_config = settings["backend"]
    sessions = [WUakeSession(name, backend_config) for name in items]
    for s in sessions:
        try:
            s.start()
        except Exception as exc:
            s.transcript.append(f"[backend error] {exc}")

    def wrap_to_width(lines: list[str], width: int) -> list[str]:
        out: list[str] = []
        for ln in lines:
            if width <= 0:
                continue
            if ln == "":
                out.append("")
                continue
            i = 0
            while i < len(ln):
                out.append(ln[i : i + width])
                i += width
        return out

    def redraw(full: bool = False) -> None:
        nonlocal hit_boxes, last_window_rect
        info = get_console_info(h_out)
        width = info.srWindow.Right - info.srWindow.Left + 1
        bottom_y = info.srWindow.Bottom
        last_window_rect = (info.srWindow.Left, info.srWindow.Top, info.srWindow.Right, info.srWindow.Bottom)

        height = info.srWindow.Bottom - info.srWindow.Top + 1
        input_y = bottom_y - 1
        text_height = max(0, height - 2)  # transcript area

        session = sessions[active]
        wrapped = wrap_to_width(session.transcript, width)
        max_scroll = max(0, len(wrapped) - text_height) if text_height > 0 else 0
        if not scroll_mode:
            session.scroll_offset = 0
        session.scroll_offset = max(0, min(session.scroll_offset, max_scroll))
        if text_height > 0:
            start = max(0, len(wrapped) - text_height - session.scroll_offset)
            end = start + text_height
            visible = wrapped[start:end]
        else:
            visible = []

        base_attr = int(info.wAttributes)
        top_y = info.srWindow.Top
        left_x = info.srWindow.Left

        if full:
            for y in range(top_y, bottom_y + 1):
                win_fill_line(h_out, left_x, y, width, " ", base_attr)

        # transcript area: clear & draw
        for row in range(0, text_height):
            y = top_y + row
            if y >= input_y:
                break
            win_fill_line(h_out, left_x, y, width, " ", base_attr)
            if row < len(visible):
                ln = visible[row][:width]
                win_write_at(h_out, left_x, y, ln, base_attr)

        # input line
        prompt = "ps> "
        win_fill_line(h_out, left_x, input_y, width, " ", base_attr)
        if scroll_mode:
            inp = "[SCROLL] PgUp/PgDn/MouseWheel, Esc = return"[:width]
        else:
            inp = (prompt + input_buf)[:width]
        win_write_at(h_out, left_x, input_y, inp, base_attr)

        # menu line with per-item reverse colors
        win_fill_line(h_out, left_x, bottom_y, width, " ", base_attr)
        hit_boxes = []
        x = 0
        for i, label in enumerate(items):
            pad = f" {label} "
            start = x
            end = x + len(pad)
            hit_boxes.append((start, end))
            item_attr = _attr_reverse(base_attr) if i == active else base_attr
            win_write_at(h_out, left_x + x, bottom_y, pad[: max(0, width - x)], item_attr)
            x = end
            if i != len(items) - 1 and x < width:
                win_write_at(h_out, left_x + x, bottom_y, " ", base_attr)
                x += 1
            if x >= width:
                break

        # cursor at end of input
        if scroll_mode:
            win_set_cursor(h_out, left_x, input_y)
        else:
            cx = min(width - 1, len(prompt) + len(input_buf))
            win_set_cursor(h_out, left_x + cx, input_y)

    try:
        enable_mouse_input(h_in)
        redraw(full=True)

        while True:
            # Some terminals do not reliably emit WINDOW_BUFFER_SIZE_EVENT.
            # Poll srWindow and redraw whenever the visible window changes.
            info_now = get_console_info(h_out)
            rect_now = (
                info_now.srWindow.Left,
                info_now.srWindow.Top,
                info_now.srWindow.Right,
                info_now.srWindow.Bottom,
            )
            need_full_redraw = last_window_rect is None or rect_now != last_window_rect
            need_redraw = need_full_redraw
            session_changed = False

            pending = get_pending_input_events(h_in)
            if pending > 0:
                events = read_console_input(h_in, max_events=min(32, pending))
            else:
                events = []
                time.sleep(0.02)

            for ev in events:
                if ev.EventType == WINDOW_BUFFER_SIZE_EVENT:
                    need_redraw = True
                    need_full_redraw = True
                    continue

                if ev.EventType == KEY_EVENT:
                    ke = ev.Event.KeyEvent
                    if not ke.bKeyDown:
                        continue
                    vk = int(ke.wVirtualKeyCode)
                    ch = ke.uChar
                    ctrl_state = int(ke.dwControlKeyState)
                    shift = bool(ctrl_state & SHIFT_PRESSED)

                    if vk == VK_ESCAPE:
                        if scroll_mode:
                            scroll_mode = False
                            sessions[active].scroll_offset = 0
                            need_redraw = True
                            session_changed = True
                            continue
                        return 0
                    if ch in ("q", "Q") and not scroll_mode:
                        return 0

                    # Session management keybindings (configurable in runner_settings.json)
                    if vk == int(kb["add_session"]["vk"]) and shift == bool(kb["add_session"]["shift"]):
                        new_name = next_session_name(items, "shell")
                        items.append(new_name)
                        s = WUakeSession(new_name, backend_config)
                        s.start()
                        sessions.append(s)
                        active = len(items) - 1
                        scroll_mode = False
                        input_buf = ""
                        save_sessions_config(cfg_path, items)
                        need_redraw = True
                        session_changed = True
                        continue

                    if vk == int(kb["delete_session"]["vk"]) and shift == bool(kb["delete_session"]["shift"]):
                        if len(items) > 1:
                            to_del = sessions.pop(active)
                            to_del.stop()
                            items.pop(active)
                            if active >= len(items):
                                active = len(items) - 1
                            scroll_mode = False
                            input_buf = ""
                            save_sessions_config(cfg_path, items)
                            need_redraw = True
                            session_changed = True
                        continue

                    if vk in (VK_PRIOR, VK_NEXT, VK_HOME, VK_END):
                        s = sessions[active]
                        scroll_mode = True
                        page = max(1, (info_now.srWindow.Bottom - info_now.srWindow.Top + 1) - 2)
                        if vk == VK_PRIOR:
                            s.scroll_offset += page
                        elif vk == VK_NEXT:
                            s.scroll_offset -= page
                        elif vk == VK_HOME:
                            s.scroll_offset = 10**9
                        elif vk == VK_END:
                            s.scroll_offset = 0
                            scroll_mode = False
                        need_redraw = True
                        continue

                    if scroll_mode:
                        continue

                    if vk == VK_BACK:
                        if input_buf:
                            input_buf = input_buf[:-1]
                            need_redraw = True
                        continue

                    if vk == VK_RETURN:
                        cmd = input_buf.strip()
                        input_buf = ""
                        need_redraw = True
                        if not cmd:
                            continue
                        if cmd.lower() in ("exit", "quit"):
                            return 0
                        sessions[active].run_command(cmd)
                        need_redraw = True
                        continue

                    if vk == VK_UP:
                        s = sessions[active]
                        if s.cmd_history:
                            if s.history_idx is None:
                                s.history_idx = len(s.cmd_history) - 1
                            else:
                                s.history_idx = max(0, s.history_idx - 1)
                            input_buf = s.cmd_history[s.history_idx]
                            need_redraw = True
                        continue

                    if vk == VK_DOWN:
                        s = sessions[active]
                        if s.cmd_history and s.history_idx is not None:
                            if s.history_idx >= len(s.cmd_history) - 1:
                                s.history_idx = None
                                input_buf = ""
                            else:
                                s.history_idx += 1
                                input_buf = s.cmd_history[s.history_idx]
                            need_redraw = True
                        continue

                    # printable character
                    if ch and ch >= " ":
                        input_buf += ch
                        need_redraw = True
                        continue

                if ev.EventType == MOUSE_EVENT:
                    me = ev.Event.MouseEvent
                    if int(me.dwEventFlags) == MOUSE_WHEELED:
                        delta = ctypes.c_short((int(me.dwButtonState) >> 16) & 0xFFFF).value
                        if delta != 0:
                            scroll_mode = True
                            page = max(1, (info_now.srWindow.Bottom - info_now.srWindow.Top + 1) - 2)
                            step = max(1, page // 3)
                            if delta > 0:
                                sessions[active].scroll_offset += step
                            else:
                                sessions[active].scroll_offset -= step
                            need_redraw = True
                        continue
                    if not (me.dwButtonState & FROM_LEFT_1ST_BUTTON_PRESSED):
                        continue

                    info = get_console_info(h_out)
                    bottom_y = info.srWindow.Bottom
                    mx = int(me.dwMousePosition.X)
                    my = int(me.dwMousePosition.Y)
                    if my != bottom_y:
                        continue

                    for idx, (sx, ex) in enumerate(hit_boxes):
                        if sx <= mx < ex:
                            if idx != active:
                                active = idx
                                input_buf = ""
                                scroll_mode = False
                                sessions[active].scroll_offset = 0
                                need_redraw = True
                                session_changed = True
                            break

            if need_redraw:
                redraw(full=need_full_redraw or session_changed)

    except KeyboardInterrupt:
        return 0
    finally:
        for s in sessions:
            s.stop()
        try:
            set_console_mode(h_in, old_in_mode)
            set_console_mode(h_out, old_out_mode)
        except Exception:
            pass
        write(reset_style() + show_cursor() + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


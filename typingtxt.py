# typingtxt.py
"""
Terminal Typing Game — Full version with:
- folder scanning menu (text/)
- loading + real preprocessing progress
- curses typing UI with highlighted next char
- real-time elapsed / accuracy / WPM updates
- smart delete (Ctrl+W) / Ctrl+Backspace mapping alternative
- manual save (Ctrl+S) to JSON, safe write
- auto-load save prompt for files (text.txt.save.json)
- score system: base points = 10 * word_length, multiplier & streak
- return-to-menu loop + exit option
Requires: Python 3.7+
On Windows: pip install windows-curses
"""
import curses
import time
import textwrap
import sys
import locale
import argparse
import os
import math
import json
import tempfile
import shutil

locale.setlocale(locale.LC_ALL, '')

# -------------------------
# Config
# -------------------------
REFRESH_INTERVAL = 0.05
WPM_DIVISOR = 5
MAX_CHARS_WARN = 800000
LOADING_MIN_SECONDS = 0.2
LOADING_MAX_SECONDS = 1.0
PREPROCESS_UPDATE_INTERVAL = 0.01
SAVE_TMP_SUFFIX = ".tmp_save"
TEXT_FOLDER = "text"

# Game score config
BASE_POINT_FACTOR = 10  # base points per char in a word
MULTIPLIER_START = 0.5
MULTIPLIER_STEP = 0.1
MULTIPLIER_MAX = 5.0

# global typed buffer
entered_buffer = []


# -------------------------
# Arg parsing
# -------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Terminal Typing Game — paste, choose from text/ or load file.")
    p.add_argument('-f', '--file', help='Path to text file to load as input (e.g. text/mytext.txt)', type=str)
    p.add_argument('-s', '--save', help='Path to save file (JSON) to load or to save to (e.g. save1.json)', type=str)
    p.add_argument('--no-loading', help='Skip loading animation (for testing)', action='store_true')
    p.add_argument('--force-width', help='Force a wrap width for preprocessing (testing)', type=int, default=None)
    return p.parse_args()


# -------------------------
# Helpers: I/O prompts
# -------------------------
def prompt_for_text_from_stdin():
    instructions = [
        "Typing Game — Paste or type your custom text.",
        "When done: press Ctrl-D (Linux/macOS) or Ctrl-Z then Enter (Windows).",
        "Leave empty to use a short sample text.",
        ">>> Start pasting text now (multi-line allowed):"
    ]
    for line in instructions:
        print(line)
    try:
        user_input = sys.stdin.read()
    except KeyboardInterrupt:
        print("\nInput cancelled. Using sample text.")
        user_input = ""

    if not user_input:
        user_input = ("The quick brown fox jumps over the lazy dog.\n"
                      "This is a sample text for the terminal typing game.\n"
                      "Feel free to paste any long passage you like (novel chapters, code, poems...).")
    if len(user_input) > MAX_CHARS_WARN:
        print(f"Note: input size is {len(user_input)} characters. This program can handle it but performance may vary.")
    return user_input


def prompt_for_text_from_file(path):
    if not os.path.isfile(path):
        print(f"File not found: {path}")
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        if not content:
            print("File is empty; using sample text instead.")
            return None
        return content
    except Exception as e:
        print(f"Error reading file {path}: {e}")
        return None


# -------------------------
# Folder scanning
# -------------------------
def ensure_text_folder(path=TEXT_FOLDER):
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass


def scan_text_folder(path=TEXT_FOLDER):
    """
    Scans the folder for .txt files, returns list of file paths (relative).
    Shows an instant visual progress bar on stdout (no delays).
    """
    ensure_text_folder(path)
    files = []
    try:
        all_entries = sorted(os.listdir(path))
    except Exception:
        return []
    txt_entries = [e for e in all_entries if e.lower().endswith('.txt') and os.path.isfile(os.path.join(path, e))]
    total = max(1, len(txt_entries))
    bar_len = 30
    sys.stdout.write("Scanning for text files...\n")
    sys.stdout.flush()
    for i, entry in enumerate(txt_entries, start=1):
        files.append(os.path.join(path, entry))
        filled = int((i / total) * bar_len)
        bar = "[" + ("#" * filled).ljust(bar_len) + "]"
        pct = (i / total) * 100
        sys.stdout.write(f"\r{bar} {pct:5.1f}%")
        sys.stdout.flush()
    if not txt_entries:
        empty_bar = "[" + (" " * bar_len) + "]"
        sys.stdout.write(f"\r{empty_bar} {0.0:5.1f}%")
        sys.stdout.flush()
    sys.stdout.write("\n")
    if files:
        print("Text files found! Which would you like to practice typing?\n")
    else:
        print("No text files found in 'text/' — defaulting to custom text input.\n")
    return files


# -------------------------
# Preprocessing (wrap + mapping)
# -------------------------
def preprocess_text(text, width, progress_callback=None):
    if width is None or width <= 0:
        width = 80
    paragraphs = text.split('\n')
    total_paragraphs = len(paragraphs)
    display_lines = []
    chars = []
    idx_to_pos = []
    last_update = time.time()
    paragraph_lengths = [len(p) for p in paragraphs]
    total_length = sum(paragraph_lengths) + 1e-9
    acc_len = 0
    for p_i, p in enumerate(paragraphs):
        if p == "":
            display_lines.append("")
        else:
            wrapped = textwrap.wrap(p, width=width, replace_whitespace=False, drop_whitespace=False)
            if not wrapped:
                display_lines.append("")
            else:
                display_lines.extend(wrapped)
        acc_len += paragraph_lengths[p_i]
        percent = min(1.0, acc_len / total_length) if total_length > 0 else 1.0
        now = time.time()
        if progress_callback and (now - last_update >= PREPROCESS_UPDATE_INTERVAL or percent >= 1.0):
            progress_callback(percent, f"Wrapping text (paragraph {p_i+1}/{total_paragraphs})")
            last_update = now
    total_lines = len(display_lines) if display_lines else 1
    acc_lines = 0
    last_update = time.time()
    for i, line in enumerate(display_lines):
        for ch in line:
            chars.append(ch)
        if i != len(display_lines) - 1:
            chars.append('\n')
        acc_lines += 1
        percent = min(1.0, acc_lines / total_lines)
        now = time.time()
        if progress_callback and (now - last_update >= PREPROCESS_UPDATE_INTERVAL or percent >= 1.0):
            progress_callback(percent, f"Building char map ({i+1}/{total_lines} lines)")
            last_update = now
    line_idx = 0
    col_idx = 0
    for ch in chars:
        idx_to_pos.append((line_idx, col_idx))
        if ch == '\n':
            line_idx += 1
            col_idx = 0
        else:
            col_idx += 1
    if progress_callback:
        progress_callback(1.0, "Preprocessing complete")
    return {
        'display_lines': display_lines,
        'chars': chars,
        'idx_to_pos': idx_to_pos,
        'total_chars': len(chars),
        'wrap_width': width
    }


def loading_and_preprocess(text, target_width=None, force_seconds=None):
    if target_width is None:
        try:
            import shutil
            target_width = shutil.get_terminal_size((80, 24)).columns - 4
            target_width = max(10, target_width)
        except Exception:
            target_width = 80
    start_time = time.time()
    state = {'pct': 0.0, 'msg': 'Starting...'}
    def progress_callback(pct, message):
        pct = max(0.0, min(1.0, float(pct)))
        state['pct'] = pct
        state['msg'] = message
        now = time.time()
        elapsed = now - start_time
        if force_seconds:
            min_time = force_seconds
        else:
            min_time = LOADING_MIN_SECONDS + min(LOADING_MAX_SECONDS, math.log1p(len(text) + 1) / 12.0 * LOADING_MAX_SECONDS)
        time_based_pct = min(1.0, elapsed / max(0.0001, min_time))
        blended = max(pct, time_based_pct * 0.6 + pct * 0.4)
        bar_total = 40
        filled = int(blended * bar_total)
        bar = "[" + ("#" * filled).ljust(bar_total) + "]"
        percent_text = f"{blended*100:5.1f}%"
        text_line = f"\r{state['msg'][:40].ljust(40)} {bar} {percent_text}"
        sys.stdout.write(text_line)
        sys.stdout.flush()
    try:
        sys.stdout.write("\nPreparing and pre-processing text...\n")
        sys.stdout.flush()
        result = preprocess_text(text, target_width, progress_callback=progress_callback)
        progress_callback(1.0, "Finalizing")
        sys.stdout.write("\nDone. Launching the typing interface...\n\n")
        sys.stdout.flush()
        time.sleep(0.08)
        return result
    except Exception as e:
        sys.stdout.write(f"\nPreprocessing failed: {e}\nProceeding without loading.\n")
        sys.stdout.flush()
        result = preprocess_text(text, target_width, progress_callback=None)
        return result


# -------------------------
# Stats & top bar
# -------------------------
def calculate_stats(correct_chars, typed_chars, start_time):
    elapsed = max(0.0001, time.time() - start_time)
    accuracy = (correct_chars / typed_chars * 100.0) if typed_chars > 0 else 100.0
    wpm = (correct_chars / WPM_DIVISOR) / (elapsed / 60.0)
    return elapsed, accuracy, wpm


def draw_top_bar(stdscr, elapsed, accuracy, wpm, progress_pct, width, score, streak, multiplier):
    status = f" Time: {elapsed:6.2f}s   Accuracy: {accuracy:6.2f}%   WPM: {wpm:6.2f} "
    score_part = f" Streak: {streak}  Mult: {multiplier:.2f}x  Score: {int(score)} "
    pb_width = min(16, max(8, width // 10))
    filled = int(progress_pct * pb_width)
    if filled >= pb_width:
        bar = "[" + ("=" * pb_width) + "]"
    else:
        bar = "[" + ("=" * filled) + (">" if filled < pb_width else "=") + ("." * (pb_width - filled - (0 if filled == pb_width else 1))) + "]"
    status = status + score_part + " " + bar
    status = status[:width]
    try:
        stdscr.addstr(0, 0, status.ljust(width), curses.color_pair(3) | curses.A_BOLD)
    except Exception:
        stdscr.addstr(0, 0, status.ljust(width))


# -------------------------
# Smart delete
# -------------------------
def is_word_char(ch):
    return ch.isalnum() or ch == '_'


def smart_delete_prev_word_buffer(buffer):
    if not buffer:
        return 0
    removed = 0
    while buffer and buffer[-1].isspace():
        buffer.pop()
        removed += 1
    if not buffer:
        return removed
    if is_word_char(buffer[-1]):
        while buffer and is_word_char(buffer[-1]):
            buffer.pop()
            removed += 1
    else:
        while buffer and (not is_word_char(buffer[-1])) and (not buffer[-1].isspace()):
            buffer.pop()
            removed += 1
        while buffer and buffer[-1].isspace():
            buffer.pop()
            removed += 1
        while buffer and is_word_char(buffer[-1]):
            buffer.pop()
            removed += 1
    return removed


# -------------------------
# Save/Load helpers
# -------------------------
def default_save_path_for_file(textfile_path):
    base = os.path.basename(textfile_path)
    dirn = os.path.dirname(textfile_path) or '.'
    savename = f"{base}.save.json"
    return os.path.join(dirn, savename)


def safe_write_json(path, data):
    tmp_path = path + SAVE_TMP_SUFFIX
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(tmp_path, path)
    except Exception:
        shutil.move(tmp_path, path)


def save_progress(save_path, metadata):
    try:
        data = metadata.copy()
        # include raw_entered so resume is exact (keeps saves slightly larger but precise)
        data['raw_entered'] = entered_buffer.copy()
        safe_write_json(save_path, data)
        return True, None
    except Exception as e:
        return False, str(e)


def load_progress_file(save_path):
    try:
        with open(save_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data, None
    except Exception as e:
        return None, str(e)


# -------------------------
# Curses UI (main game)
# -------------------------
def main_curses(stdscr, preprocess_result, save_path=None):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    curses.use_default_colors()
    try:
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_RED, -1)
        curses.init_pair(3, curses.COLOR_CYAN, -1)
        curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    except Exception:
        pass

    display_lines = preprocess_result.get('display_lines', [])
    chars = preprocess_result.get('chars', [])
    idx_to_pos = preprocess_result.get('idx_to_pos', [])
    total_chars = preprocess_result.get('total_chars', 0)
    wrap_width = preprocess_result.get('wrap_width', None)

    height, width = stdscr.getmaxyx()
    text_win_top = 2
    text_win_height = height - text_win_top - 3
    text_win_width = max(10, width - 4)

    position = 0
    start_time = None
    last_draw = 0.0

    # Score/state initialization
    score = 0.0
    streak = 0
    multiplier = MULTIPLIER_START

    # loaded state restore
    loaded_state = preprocess_result.get('loaded_state') if preprocess_result else None
    if loaded_state:
        position = min(int(loaded_state.get('position', 0)), total_chars)
        # if raw_entered provided, restore exact entered_buffer
        raw = loaded_state.get('raw_entered', None)
        entered_buffer.clear()
        if isinstance(raw, list):
            for ch in raw:
                entered_buffer.append(ch)
        else:
            # fallback: reconstruct expected chars up to position
            for i in range(min(position, len(chars))):
                entered_buffer.append(chars[i])
        score = float(loaded_state.get('score', 0.0))
        streak = int(loaded_state.get('streak', 0))
        multiplier = float(loaded_state.get('multiplier', MULTIPLIER_START))
        # start_time set so elapsed shows saved elapsed (if present)
        saved_elapsed = float(loaded_state.get('elapsed_time', 0.0))
        start_time = time.time() - saved_elapsed

    if not idx_to_pos and chars:
        line = 0
        col = 0
        for ch in chars:
            idx_to_pos.append((line, col))
            if ch == '\n':
                line += 1
                col = 0
            else:
                col += 1

    def compute_stats():
        typed = len(entered_buffer)
        correct = sum(1 for i, e in enumerate(entered_buffer) if i < len(chars) and e == chars[i])
        incorrect = typed - correct
        return typed, correct, incorrect

    def award_word_if_correct(end_index):
        """
        Called when a separator (space or newline) is typed at index end_index (inclusive),
        i.e., the last typed char index is end_index and chars[end_index].isspace() is True.
        Checks the word before it and awards score if all chars matched.
        Returns True if awarded, False otherwise.
        """
        nonlocal score, streak, multiplier
        # find start of word
        i = end_index - 1
        while i >= 0 and not chars[i].isspace():
            i -= 1
        word_start = i + 1
        word_end = end_index  # exclusive of separator
        word_len = word_end - word_start
        if word_len <= 0:
            return False
        # check if buffer contains entered chars for that range
        if len(entered_buffer) < word_end:
            return False
        # check correctness for the whole word
        correct_word = True
        for k in range(word_start, word_end):
            if entered_buffer[k] != chars[k]:
                correct_word = False
                break
        if correct_word:
            base_points = BASE_POINT_FACTOR * word_len
            gained = base_points * multiplier
            score += gained
            streak += 1
            multiplier = min(MULTIPLIER_MAX, multiplier + MULTIPLIER_STEP)
            return True
        else:
            return False

    def reset_streak_due_to_error():
        nonlocal streak, multiplier
        streak = 0
        multiplier = MULTIPLIER_START

    def draw():
        nonlocal last_draw
        stdscr.erase()
        typed_now, correct_now, incorrect_now = compute_stats()
        elapsed_now = (time.time() - start_time) if start_time else 0.0
        accuracy_now = (correct_now / typed_now * 100.0) if typed_now > 0 else 100.0
        wpm_now = (correct_now / WPM_DIVISOR) / (elapsed_now / 60.0) if start_time and elapsed_now > 0 else 0.0
        progress_pct = position / total_chars if total_chars > 0 else 1.0
        draw_top_bar(stdscr, elapsed_now, accuracy_now, wpm_now, progress_pct, width, score, streak, multiplier)
        if total_chars == 0:
            try:
                stdscr.addstr(text_win_top, 0, "(No text provided)".ljust(width))
                stdscr.refresh()
                return
            except Exception:
                return
        cur_line, cur_col = idx_to_pos[position] if position < len(idx_to_pos) else idx_to_pos[-1]
        half = text_win_height // 2
        start_line = max(0, cur_line - half)
        end_line = start_line + text_win_height
        max_display_line = max(0, idx_to_pos[-1][0]) if idx_to_pos else 0
        if end_line > max_display_line + 1:
            end_line = max_display_line + 1
            start_line = max(0, end_line - text_win_height)
        typed_map = {}
        for i, entry in enumerate(entered_buffer):
            if i >= len(chars):
                break
            p_line, p_col = idx_to_pos[i]
            expected = chars[i]
            typed_map[(p_line, p_col)] = (entry, entry == expected)
        visible_lines = display_lines[start_line:end_line]
        for ln, content in enumerate(visible_lines, start=start_line):
            y = text_win_top + (ln - start_line)
            x = 2
            for col_idx, ch in enumerate(content):
                pos = (ln, col_idx)
                if pos in typed_map:
                    entry_char, is_correct = typed_map[pos]
                    if is_correct:
                        try:
                            stdscr.addstr(y, x, entry_char, curses.color_pair(1))
                        except Exception:
                            stdscr.addstr(y, x, entry_char)
                    else:
                        try:
                            stdscr.addstr(y, x, entry_char, curses.color_pair(2) | curses.A_UNDERLINE)
                        except Exception:
                            stdscr.addstr(y, x, entry_char)
                else:
                    try:
                        stdscr.addstr(y, x, ch, curses.color_pair(5))
                    except Exception:
                        stdscr.addstr(y, x, ch)
                x += 1
            try:
                stdscr.addstr(y, x, " " * max(0, width - x - 1))
            except Exception:
                pass
        if position < len(chars):
            cursor_line, cursor_col = idx_to_pos[position]
            if start_line <= cursor_line < end_line:
                y = text_win_top + (cursor_line - start_line)
                x = 2 + cursor_col
                blink_on = (int(time.time() * 2) % 2) == 0
                ch = chars[position]
                display_ch = '¶' if ch == '\n' else ch
                try:
                    if blink_on:
                        stdscr.addstr(y, x, display_ch, curses.color_pair(4) | curses.A_BOLD)
                    else:
                        stdscr.addstr(y, x, display_ch, curses.A_REVERSE)
                except Exception:
                    stdscr.addstr(y, x, display_ch)
        footer = " ESC to quit early | Backspace supported | Ctrl+W SmartDel | Ctrl+S Save | Return->Menu after finish"
        try:
            stdscr.addstr(height - 1, 0, footer[:width].ljust(width), curses.A_DIM)
        except Exception:
            pass
        stdscr.refresh()
        last_draw = time.time()

    # main loop
    last_time = time.time()
    while True:
        now = time.time()
        try:
            ch = stdscr.get_wch()
        except curses.error:
            ch = None
        if ch is not None:
            if start_time is None:
                start_time = time.time()
            if isinstance(ch, str):
                ordch = ord(ch) if ch else None
                if ordch == 27:  # ESC
                    break
                if ordch == 19:  # Ctrl+S => manual save
                    typed_now, correct_now, incorrect_now = compute_stats()
                    elapsed_now = (time.time() - start_time) if start_time else 0.0
                    metadata = {
                        'filename': preprocess_result.get('source_filename', None),
                        'position': position,
                        'elapsed_time': elapsed_now,
                        'correct': correct_now,
                        'incorrect': incorrect_now,
                        'score': score,
                        'streak': streak,
                        'multiplier': multiplier,
                        'timestamp': time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                        'wrap_width': wrap_width
                    }
                    if save_path:
                        save_to = save_path
                    else:
                        src = preprocess_result.get('source_filename', None)
                        if src:
                            save_to = default_save_path_for_file(src)
                        else:
                            save_to = "typing_save.json"
                    ok, err = save_progress(save_to, metadata)
                    if ok:
                        try:
                            stdscr.addstr(height - 2, 0, f"Saved to: {save_to}".ljust(width), curses.A_BOLD)
                            stdscr.refresh()
                        except Exception:
                            pass
                        time.sleep(0.5)
                    else:
                        try:
                            stdscr.addstr(height - 2, 0, f"Save failed: {err}".ljust(width), curses.A_BOLD)
                            stdscr.refresh()
                        except Exception:
                            pass
                        time.sleep(1.0)
                    continue
                if ordch == 23:  # Ctrl+W smart delete
                    removed = smart_delete_prev_word_buffer(entered_buffer)
                    position = max(0, position - removed)
                    continue
                if ordch in (8, 127):  # backspace
                    if entered_buffer:
                        entered_buffer.pop()
                        position = max(0, position - 1)
                    continue
                if ordch in (10, 13):  # enter/newline typed
                    entered_buffer.append('\n')
                    position += 1
                    # If expected was separator and the word before is correct, award
                    if position - 1 < len(chars) and chars[position - 1].isspace():
                        award_word_if_correct(position - 1)
                    continue
                # regular printable char
                # check correctness for streak reset
                expected_char = chars[position] if position < len(chars) else None
                entered_buffer.append(ch)
                position += 1
                if expected_char is None or ch != expected_char:
                    # wrong char typed
                    reset_streak_due_to_error()
                # if typed char is separator, evaluate word correctness
                if position - 1 < len(chars) and chars[position - 1].isspace():
                    award_word_if_correct(position - 1)
            else:
                # special curses keys
                if ch == curses.KEY_BACKSPACE:
                    if entered_buffer:
                        entered_buffer.pop()
                        position = max(0, position - 1)
                elif ch == curses.KEY_EXIT:
                    break
                else:
                    pass
        # completion check
        if position >= total_chars:
            # finished typing entire text
            break
        # redraw
        if now - last_draw >= REFRESH_INTERVAL:
            draw()
        time.sleep(0.01)

    # final stats
    typed_chars_final, correct_chars_final, incorrect_chars_final = compute_stats()
    if start_time is None:
        start_time = time.time()
    elapsed, accuracy, wpm = calculate_stats(correct_chars_final, typed_chars_final if typed_chars_final > 0 else 1, start_time)

    # final summary screen
    stdscr.erase()
    summary_lines = [
        "Typing session finished!",
        f"Time elapsed: {elapsed:0.2f} seconds",
        f"Characters typed: {typed_chars_final}",
        f"Correct characters: {correct_chars_final}",
        f"Incorrect characters: {incorrect_chars_final}",
        f"Accuracy: {accuracy:0.2f}%",
        f"WPM (approx): {wpm:0.2f}",
        f"Score: {int(score)}   Streak: {streak}   Multiplier: {multiplier:.2f}x"
    ]
    for i, line in enumerate(summary_lines):
        try:
            stdscr.addstr(2 + i, 2, line, curses.A_BOLD if i == 0 else 0)
        except Exception:
            pass
    try:
        stdscr.addstr(12, 2, "Press any key to continue...", curses.A_DIM)
    except Exception:
        pass
    stdscr.nodelay(False)
    stdscr.getch()

    # return session outcome so main can ask for next action (we'll return key stats)
    return {
        'position': position,
        'elapsed_time': time.time() - start_time if start_time else 0.0,
        'correct': correct_chars_final,
        'incorrect': incorrect_chars_final,
        'score': score,
        'streak': streak,
        'multiplier': multiplier,
        'raw_entered': entered_buffer.copy()
    }


# -------------------------
# Small helper used inside curses for stats
# -------------------------
def compute_local_stats(chars_list):
    typed = len(entered_buffer)
    correct = sum(1 for i, e in enumerate(entered_buffer) if i < len(chars_list) and e == chars_list[i])
    incorrect = typed - correct
    return typed, correct, incorrect


# -------------------------
# Main menu and flow
# -------------------------
def choose_text_from_folder_interactive():
    files = scan_text_folder(TEXT_FOLDER)
    if not files:
        return None, None
    for idx, fp in enumerate(files, start=1):
        print(f"[{idx}] {os.path.basename(fp)}")
    print("[C] I want to have a custom text to be typed by me or pasted by me")
    print("[E] Exit program")
    choice = None
    try:
        choice = input("\nChoose a file number, 'C' for custom, or 'E' to exit: ").strip()
    except Exception:
        choice = 'C'
    if not choice:
        choice = 'C'
    if choice.lower() == 'c':
        txt = prompt_for_text_from_stdin()
        return txt, None
    if choice.lower() == 'e':
        return None, 'exit'
    try:
        n = int(choice)
        if 1 <= n <= len(files):
            src = files[n - 1]
            content = prompt_for_text_from_file(src)
            if content is None:
                print("Failed to read selected file; falling back to custom paste.")
                content = prompt_for_text_from_stdin()
                return content, None
            else:
                return content, src
        else:
            print("Invalid selection; falling back to custom paste.")
            content = prompt_for_text_from_stdin()
            return content, None
    except Exception:
        print("Invalid selection; falling back to custom paste.")
        content = prompt_for_text_from_stdin()
        return content, None


def main():
    args = parse_args()
    exit_program = False
    # Outer loop: allow returning to menu after sessions until user exits
    while not exit_program:
        source_filename = None
        specified_save_path = args.save if args.save else None
        text = None

        # If -f given and this is the first run, load that file directly
        if args.file:
            source_filename = args.file
            file_content = prompt_for_text_from_file(args.file)
            if file_content is None:
                print("Falling back to paste input method.")
                text = prompt_for_text_from_stdin()
            else:
                text = file_content
        else:
            # No -f: show folder menu
            txt_choice, maybe_src = choose_text_from_folder_interactive()
            if maybe_src == 'exit':
                print("Exiting program. Goodbye!")
                return
            text = txt_choice
            if maybe_src:
                source_filename = maybe_src

        if text is None:
            # If somehow still none, exit
            print("No text selected. Exiting.")
            return

        # Normalize line endings
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        if len(text) > MAX_CHARS_WARN:
            print(f"Large input detected: {len(text)} characters. This can be handled but may be slower.")

        target_width = args.force_width if args.force_width else None

        # Save auto-detect & load prompt when we have a source file
        loaded_state = None
        if source_filename:
            default_save = default_save_path_for_file(source_filename)
            if specified_save_path:
                if os.path.exists(specified_save_path):
                    data, err = load_progress_file(specified_save_path)
                    if data:
                        loaded_state = data
                        print(f"Loaded save from {specified_save_path}. Progress will be restored.")
                    else:
                        print(f"Failed to load save file {specified_save_path}: {err}")
            else:
                if os.path.exists(default_save):
                    ans = None
                    try:
                        ans = input(f"Found a previous save for '{source_filename}' at '{default_save}'. Continue where you left off? (y/n): ").strip().lower()
                    except Exception:
                        ans = 'n'
                    if ans and ans.startswith('y'):
                        data, err = load_progress_file(default_save)
                        if data:
                            loaded_state = data
                            specified_save_path = default_save
                            print("Save loaded. Progress will be restored in the typing interface.")
                        else:
                            print(f"Failed to load save file {default_save}: {err}")
                    else:
                        print("Starting fresh (not loading save).")

        # Loading + preprocessing (unless disabled)
        preprocess_result = None
        if not args.no_loading:
            try:
                preprocess_result = loading_and_preprocess(text, target_width)
                preprocess_result['source_filename'] = source_filename
                if loaded_state:
                    preprocess_result['loaded_state'] = loaded_state
            except Exception:
                try:
                    preprocess_result = preprocess_text(text, target_width, progress_callback=None)
                    preprocess_result['source_filename'] = source_filename
                    if loaded_state:
                        preprocess_result['loaded_state'] = loaded_state
                except Exception as e:
                    print("Preprocessing failed entirely:", e)
                    preprocess_result = {'display_lines': [text[:80]], 'chars': list(text), 'idx_to_pos': [], 'total_chars': len(text), 'wrap_width': target_width or 80, 'source_filename': source_filename}
                    if loaded_state:
                        preprocess_result['loaded_state'] = loaded_state
        else:
            print("Preprocessing text (no loading animation)...")
            preprocess_result = preprocess_text(text, target_width, progress_callback=None)
            preprocess_result['source_filename'] = source_filename
            if loaded_state:
                preprocess_result['loaded_state'] = loaded_state
            print("Preprocessing done.")

        # If loaded_state exists and contains raw_entered, restore entered_buffer. Otherwise best-effort
        if loaded_state:
            raw_entered = loaded_state.get('raw_entered', None)
            entered_buffer.clear()
            if isinstance(raw_entered, list):
                for ch in raw_entered:
                    entered_buffer.append(ch)
            else:
                # assume perfect typing up to position as fallback
                pos = int(loaded_state.get('position', 0))
                chars_list = preprocess_result.get('chars', [])
                for i in range(min(pos, len(chars_list))):
                    entered_buffer.append(chars_list[i])

        # Launch curses UI, which returns session outcome
        try:
            session_outcome = curses.wrapper(main_curses, preprocess_result, save_path=specified_save_path)
        except Exception as e:
            print("An error occurred during the terminal UI session.")
            print("If you're on Windows, ensure 'windows-curses' is installed (pip install windows-curses).")
            print("Error:", e)
            return

        # After session, session_outcome is a dict with position, elapsed_time, score, streak, multiplier, raw_entered, etc.
        # Ask the user what to do next
        # Offer choices: choose another text, paste custom, exit
        next_choice = None
        try:
            print("\nWhat would you like to do next?")
            print("[1] Choose another text to practice")
            print("[2] Enter/paste a custom text to practice")
            print("[3] Exit program")
            next_choice = input("Choose 1/2/3: ").strip()
        except Exception:
            next_choice = '3'
        if not next_choice:
            next_choice = '3'
        if next_choice == '1':
            # go back to top of loop — since we retained args, it will show folder menu again
            # optionally, we can save the session outcome if user wants (but save is manual via Ctrl+S)
            continue
        elif next_choice == '2':
            # prompt for paste in next loop iteration by forcing args.file to None and setting text via prompt
            # easiest is to set args.file to None and in next iteration choose custom by not using scan
            # We'll just loop and let choose_text_from_folder_interactive handle custom; user can select 'C'
            continue
        else:
            print("Exiting program. Goodbye!")
            return


if __name__ == "__main__":
    main()

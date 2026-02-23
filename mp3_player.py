import pygame
import os
import random
import tkinter as tk
from tkinter import filedialog, ttk
import time
import threading
import json
from pathlib import Path
try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except Exception:
    KEYBOARD_AVAILABLE = False
import psutil


try:
    pygame.mixer.init()
except Exception as e:
    print("Audio init failed:", e)

pygame.mixer.init()

playlist = []
filtered_playlist = []
index = 0
playing = False
paused = False
volume = 0.1
slider_dragging = False
track_duration = 0
seek_block_until = 0
playback_offset = 0
_listened_flag = False
auto_adjust_enabled = False
auto_thread = None
auto_stop_event = threading.Event()
seeded_shuffle_enabled = False
shuffle_seed = None
base_playlist = []

debug_window = None
debug_labels = {}
debug_updating = False

process = psutil.Process(os.getpid())


BASE_DIR = Path(__file__).resolve().parent
stats_file = BASE_DIR / "song_stats.json"


if stats_file.exists():
    try:
        with open(stats_file, 'r', encoding='utf-8') as f:
            song_stats = json.load(f)
    except Exception:
        song_stats = {}
else:
    song_stats = {}

def save_stats():
    try:
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(song_stats, f, indent=2)
    except Exception:
        pass

def get_stats_for_path(path):
    name = os.path.basename(path)
    return song_stats.get(name, {'started': 0, 'listened': 0, 'skipped': 0})

def increment_stat_for_path(path, key):
    name = os.path.basename(path)
    if name not in song_stats:
        song_stats[name] = {'started': 0, 'listened': 0, 'skipped': 0}
    song_stats[name][key] = song_stats[name].get(key, 0) + 1
    save_stats()

root = tk.Tk()
root.title("Python MP3 Player")
root.geometry("560x540")
root.minsize(400, 400)
root.rowconfigure(1, weight=1)
root.columnconfigure(0, weight=1)

def toggle_button(btn, var, command=None):
    var.set(not var.get())
    apply_toggle_button_style(btn, var)
    if command:
        command()

def apply_toggle_button_style(btn, var):
    if dark_mode:
        btn.config(
            bg=DARK_BTN_ON if var.get() else DARK_BTN_OFF,
            fg=DARK_BTN_FG,
            activebackground=DARK_BTN_ON,
            activeforeground=DARK_BTN_FG,
            relief="sunken" if var.get() else "raised"
        )
    else:
        btn.config(
            bg=LIGHT_BTN_ON if var.get() else LIGHT_BTN_OFF,
            fg=LIGHT_BTN_FG,
            activebackground=LIGHT_BTN_ON,
            activeforeground=LIGHT_BTN_FG,
            relief="sunken" if var.get() else "raised"
        )


###########################
# Search Bar
###########################
search_frame = tk.Frame(root)
search_frame.pack(pady=6)

search_label = tk.Label(search_frame, text="Search:")
search_label.pack(side='left', padx=(0, 5))

search_var = tk.StringVar()
search_entry = tk.Entry(search_frame, textvariable=search_var, width=40)
search_entry.pack(side='left')

############################
#Playback buttons
############################
def toggle_play():
    global playing, paused
    if not playlist:
        return
    if playing and not paused:
        pygame.mixer.music.pause()
        paused = True
        btn_play.config(text='▶ Resume')
    elif paused:
        pygame.mixer.music.unpause()
        paused = False
        btn_play.config(text='⏸ Pause')
    else:
        play_track(index)

def play_next():
    global index, _listened_flag
    if not playlist:
        return
    if not _listened_flag:
        increment_stat_for_path(playlist[index], 'skipped')
    index = (index + 1) % len(playlist)
    play_track(index)

def play_prev():
    global index, _listened_flag
    if not playlist:
        return
    if not _listened_flag:
        increment_stat_for_path(playlist[index], 'skipped')
    index = (index - 1) % len(playlist)
    play_track(index)

###########################
# Playlist Box
###########################
playlist_box = tk.Listbox(root, selectmode=tk.SINGLE, width=60)
playlist_box.pack(fill="both", expand=True, padx=20, pady=16)

status_label = tk.Label(root, text="No track loaded", anchor="w")
status_label.pack(fill="x")

progress_slider = ttk.Scale(root, from_=0, to=1, orient="horizontal", length=500)
progress_slider.pack(fill="x", expand=False, padx=10, pady=10)

control_frame = tk.Frame(root)
control_frame.pack()

btn_prev = tk.Button(control_frame, text="⏮ Prev", command=play_prev)
btn_prev.grid(row=0, column=0, padx=6)

btn_play = tk.Button(control_frame, text="▶ Play", command=toggle_play)
btn_play.grid(row=0, column=1, padx=6)

btn_next = tk.Button(control_frame, text="⏭ Next", command=play_next)
btn_next.grid(row=0, column=2, padx=6)

volume_frame = tk.Frame(root)
volume_frame.pack(pady=8)

volume_label = tk.Label(volume_frame, text='Volume')
volume_label.pack(side='left')

volume_slider = ttk.Scale(volume_frame, from_=0, to=1, orient='horizontal', length=300)
volume_slider.set(volume)
volume_slider.pack(side='left', padx=8)

###########################
# Mode Toggles
###########################
auto_frame = tk.Frame(root)
auto_frame.pack(pady=6)

auto_var = tk.BooleanVar(value=False)
show_stats_var = tk.BooleanVar(value=False)

def toggle_auto():
    if auto_var.get():
        start_auto_adjust()
    else:
        stop_auto_adjust()

def toggle_show_stats():
    refresh_playlist_box()

schizo_btn = tk.Button(
    auto_frame,
    text="Schizo mode",
    width=14,
    command=lambda: toggle_button(schizo_btn, auto_var, toggle_auto)
)
schizo_btn.pack(side="left", padx=8)

stats_btn = tk.Button(
    auto_frame,
    text="Show Stats",
    width=14,
    command=lambda: toggle_button(stats_btn, show_stats_var, toggle_show_stats)
)
stats_btn.pack(side="left", padx=8)



###########################
# Playlist Logic
###########################
def apply_shuffle():
    global playlist, filtered_playlist, index

    if not base_playlist:
        return

    playlist = base_playlist.copy()

    if seeded_shuffle_enabled and shuffle_seed is not None:
        rng = random.Random(shuffle_seed)
        rng.shuffle(playlist)
    else:
        random.shuffle(playlist)

    filtered_playlist = playlist.copy()

    index = 0
    refresh_playlist_box()



def load_folder():
    global playlist, base_playlist, filtered_playlist

    root.update()
    folder = filedialog.askdirectory(parent=root)
    if not folder:
        return


    base_playlist = sorted(
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith('.mp3')
    )

    apply_shuffle()
    filtered_playlist = playlist.copy()
    play_track(0)

def refresh_playlist_box():
    playlist_box.delete(0, tk.END)
    for song in filtered_playlist:
        name = os.path.basename(song)
        if show_stats_var.get():
            s = get_stats_for_path(song)
            name = f"{name} | ▶{s['started']} 🎧{s['listened']} ⏭{s['skipped']}"
        playlist_box.insert(tk.END, name)

###########################
# Seeded Shuffle Controls
###########################
def estimate_bitrate(filepath):
    try:
        size_bytes = os.path.getsize(filepath)
        if track_duration > 0:
            return int((size_bytes * 8) / track_duration / 1000)
    except Exception:
        pass
    return 0

def update_debug_stats():
    global debug_updating

    if not debug_updating:
        return

    try:
            current_path = playlist[index] if playlist else None

            debug_labels["Track"].config(
                text=os.path.basename(current_path) if current_path else "None"
            )
            debug_labels["Playing"].config(text=str(playing))
            debug_labels["Paused"].config(text=str(paused))
            debug_labels["Volume"].config(text=f"{int(volume*100)}%")
            debug_labels["Track Duration"].config(text=f"{round(track_duration,2)}s")

            pos = pygame.mixer.music.get_pos()
            pos_s = (pos / 1000.0 if pos >= 0 else 0) + playback_offset
            debug_labels["Playback Position"].config(text=f"{round(pos_s,2)}s")

            if current_path:
                debug_labels["Bitrate (est)"].config(
                    text=f"{estimate_bitrate(current_path)} kbps"
                )
                cpu = process.cpu_percent(interval=None)

                mem = process.memory_info().rss / (1024 * 1024)  # MB

                try:
                    io = process.io_counters()
                    disk_read = io.read_bytes / (1024 * 1024)
                    disk_write = io.write_bytes / (1024 * 1024)
                except Exception:
                    disk_read = disk_write = 0


                debug_labels["CPU %"].config(text=f"{cpu:.2f}%")
                debug_labels["RAM %"].config(text=f"{mem:.1f} MB")
                debug_labels["Disk %"].config(
                    text=f"R {disk_read:.1f} MB / W {disk_write:.1f} MB"
                )

            debug_labels["Threads"].config(text=str(threading.active_count()))
            debug_labels["Playlist Size"].config(text=str(len(playlist)))
            debug_labels["Filtered Size"].config(text=str(len(filtered_playlist)))

    except Exception:
            pass

    root.after(1000, update_debug_stats)

def open_debug_window():
    global debug_window, debug_labels, debug_updating

    if debug_window and tk.Toplevel.winfo_exists(debug_window):
        debug_window.lift()
        return

    debug_window = tk.Toplevel(root)
    debug_window.title("MP3 Debug")
    debug_window.geometry("420x360")

    frame = tk.Frame(debug_window)
    frame.pack(fill="both", expand=True, padx=10, pady=10)

    fields = [
        "Track",
        "Playing",
        "Paused",
        "Volume",
        "Bitrate (est)",
        "Track Duration",
        "Playback Position",
        "Next Schizo Volume Change",
        "CPU %",
        "RAM %",
        "Disk %",
        "Threads",
        "Playlist Size",
        "Filtered Size"
    ]

    debug_labels = {}
    for f in fields:
        row = tk.Frame(frame)
        row.pack(anchor="w", fill="x", pady=2)
        tk.Label(row, text=f + ":", width=22, anchor="w").pack(side="left")
        val = tk.Label(row, text="—", anchor="w")
        val.pack(side="left")
        debug_labels[f] = val

    debug_updating = True
    update_debug_stats()

    def on_close():
        global debug_updating
        debug_updating = False
        debug_window.destroy()

    debug_window.protocol("WM_DELETE_WINDOW", on_close)

seed_var = tk.StringVar()
seed_enable_var = tk.BooleanVar(value=False)

def apply_seed():
    global seeded_shuffle_enabled, shuffle_seed

    text = seed_var.get().strip()

    if text == "-debug":
        open_debug_window()
        return

    seeded_shuffle_enabled = seed_enable_var.get()
    shuffle_seed = text or None

    apply_shuffle()

    if playlist:
        play_track(0)

seed_frame = tk.Frame(root)
seed_frame.pack(pady=6)

seed_btn = tk.Button(
    seed_frame,
    text="Seeded Shuffle",
    width=14,
    command=lambda: toggle_button(seed_btn, seed_enable_var)
)
seed_btn.pack(side="left", padx=4)

seed_entry = tk.Entry(
    seed_frame,
    textvariable=seed_var,
    width=18
)
seed_entry.pack(side="left", padx=4)

seed_apply_btn = tk.Button(
    seed_frame,
    text="Apply",
    command=apply_seed
)
seed_apply_btn.pack(side="left", padx=4)



###########################
# Search Logic
###########################
def update_search_results(*args):
    global filtered_playlist
    query = search_var.get().lower()
    if not query:
        filtered_playlist = playlist.copy()
    else:
        filtered_playlist = [s for s in playlist if query in os.path.basename(s).lower()]
    refresh_playlist_box()

def play_first_search_result(event=None):
    if filtered_playlist:
        play_track(playlist.index(filtered_playlist[0]))

search_var.trace_add('write', update_search_results)
search_entry.bind('<Return>', play_first_search_result)

###########################
# Playback Functions
###########################
def play_track(i, position=None):
    global index, playing, paused, track_duration, playback_offset, _listened_flag
    if not playlist:
        return
    index = i % len(playlist)
    filepath = playlist[index]
    increment_stat_for_path(filepath, 'started')
    _listened_flag = False
    try:
        pygame.mixer.music.load(filepath)
    except Exception as e:
        print("Failed loading:", filepath, e)
        return
    pygame.mixer.music.play(0)
    pygame.mixer.music.set_volume(volume)
    playback_offset = 0
    if position is not None:
        try:
            pygame.mixer.music.set_pos(position)
            playback_offset = position
        except Exception:
            pass
    playing = True
    paused = False
    try:
        track_duration = pygame.mixer.Sound(filepath).get_length()
    except Exception:
        track_duration = 0
    update_ui_state()
    update_status_label()
    playlist_box.select_clear(0, tk.END)
    if filepath in filtered_playlist:
        playlist_box.select_set(filtered_playlist.index(filepath))
        playlist_box.activate(filtered_playlist.index(filepath))

def play_selected():
    selection = playlist_box.curselection()
    if selection:
        selected_name = playlist_box.get(selection[0]).split('|')[0].strip()
        for i, path in enumerate(playlist):
            if os.path.basename(path) == selected_name:
                play_track(i)
                break

playlist_box.bind("<Double-Button-1>", lambda e: play_selected())

###########################
# Volume Control
###########################
def change_volume(e=None):
    global volume
    volume = float(volume_slider.get())
    pygame.mixer.music.set_volume(volume)
    status_label.config(text=f"Volume: {int(volume*100)}%")
    root.after(1200, update_status_label)

volume_slider.bind('<ButtonRelease-1>', change_volume)
volume_slider.bind('<B1-Motion>', change_volume)

###########################
# Slider Seeking
###########################
def start_drag(event):
    global slider_dragging
    slider_dragging = True

def stop_drag(event):
    global slider_dragging, seek_block_until, playback_offset
    slider_dragging = False
    if playing and playlist:
        new_pos = progress_slider.get() * track_duration
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(playlist[index])
            pygame.mixer.music.play(start=new_pos)
            pygame.mixer.music.set_volume(volume)
            playback_offset = new_pos
            seek_block_until = time.time() + 1.0
        except Exception as e:
            print("Seek failed:", e)

progress_slider.bind("<ButtonPress-1>", start_drag)
progress_slider.bind("<ButtonRelease-1>", stop_drag)

###########################
# Auto-volume adjuster
###########################

def schedule_next_adjust():
    return random.randint(5*60, 30*60)

def auto_adjust_loop():
    while not auto_stop_event.is_set():
        wait = schedule_next_adjust()
        slept = 0
        while slept < wait and not auto_stop_event.is_set():
            time.sleep(1)
            slept += 1
        if auto_stop_event.is_set():
            break
        change = 0.0 if random.choice([True, False]) else -0.03
        new_vol = max(0.0, min(1.0, volume + change))
        def apply_volume():
            global volume
            volume = new_vol
            pygame.mixer.music.set_volume(volume)
            volume_slider.set(volume)
            status_label.config(text=f'Auto-adjusted volume to {int(volume*100)}%')
            root.after(100, update_status_label)
        root.after(0, apply_volume)

def start_auto_adjust():
    global auto_adjust_enabled, auto_thread, auto_stop_event
    if auto_adjust_enabled:
        return
    auto_adjust_enabled = True
    auto_stop_event.clear()
    auto_thread = threading.Thread(target=auto_adjust_loop, daemon=True)
    auto_thread.start()

def stop_auto_adjust():
    global auto_adjust_enabled, auto_thread, auto_stop_event
    if not auto_adjust_enabled:
        return
    auto_stop_event.set()
    auto_thread = None
    auto_adjust_enabled = False

###########################
# Dark Mode
###########################

dark_mode = True
style = ttk.Style()

LIGHT_BTN_OFF = "#f0f0f0"
LIGHT_BTN_ON  = "#6a9fb5"
LIGHT_BTN_FG  = "#000000"
DARK_BTN_OFF = "#444444"
DARK_BTN_ON  = "#6a9fb5"
DARK_BTN_FG  = "#ffffff"

def set_dark_mode_styles():
    style.theme_use('default')
    style.configure('TCheckbutton', background='#2e2e2e', foreground='white')
    style.configure('TScale', troughcolor='#555555', background='#2e2e2e')

def set_light_mode_styles():
    style.theme_use('default')
    style.configure('TCheckbutton', background='#f0f0f0', foreground='black')
    style.configure('TScale', troughcolor='#d9d9d9', background='#f0f0f0')

def apply_dark_mode():
    bg_color = '#2e2e2e'
    fg_color = '#ffffff'
    btn_bg = '#444444'
    entry_bg = '#3a3a3a'
    entry_fg = '#ffffff'

    bottom_btn_frame.configure(bg=bg_color)

    apply_toggle_button_style(schizo_btn, auto_var)
    apply_toggle_button_style(stats_btn, show_stats_var)
    apply_toggle_button_style(seed_btn, seed_enable_var)

    set_dark_mode_styles()
    root.configure(bg=bg_color)
    playlist_box.configure(bg='#3e3e3e', fg=fg_color, selectbackground='#666666', selectforeground=fg_color)
    status_label.configure(bg=bg_color, fg=fg_color)
    volume_label.configure(bg=bg_color, fg=fg_color)
    control_frame.configure(bg=bg_color)
    volume_frame.configure(bg=bg_color)
    auto_frame.configure(bg=bg_color)
    search_frame.configure(bg=bg_color)
    search_label.configure(bg=bg_color, fg=fg_color)
    search_entry.configure(bg=entry_bg, fg=entry_fg, insertbackground=entry_fg, highlightbackground='#555555', highlightcolor='#777777', relief='flat')
    for btn in [btn_prev, btn_play, btn_next, btn_load, darkmode_btn]:
        btn.configure(bg=btn_bg, fg=fg_color, activebackground='#555555')
    seed_frame.configure(bg=bg_color)

    seed_entry.configure(
        bg=entry_bg,
        fg=entry_fg,
        insertbackground=entry_fg,
        highlightbackground='#555555',
        highlightcolor='#777777',
        relief='flat'
    )

    seed_apply_btn.configure(
        bg=btn_bg,
        fg=fg_color,
        activebackground='#555555'
    )

def apply_light_mode():
    bg_color = '#f0f0f0'
    fg_color = '#000000'
    btn_bg = '#f0f0f0'
    entry_bg = '#ffffff'
    entry_fg = '#000000'


    apply_toggle_button_style(schizo_btn, auto_var)
    apply_toggle_button_style(stats_btn, show_stats_var)
    apply_toggle_button_style(seed_btn, seed_enable_var)
    
    bottom_btn_frame.configure(bg=bg_color)

    set_light_mode_styles()
    root.configure(bg=bg_color)
    playlist_box.configure(bg='white', fg=fg_color, selectbackground='#c0c0ff', selectforeground=fg_color)
    status_label.configure(bg=bg_color, fg=fg_color)
    volume_label.configure(bg=bg_color, fg=fg_color)
    control_frame.configure(bg=bg_color)
    volume_frame.configure(bg=bg_color)
    auto_frame.configure(bg=bg_color)
    search_frame.configure(bg=bg_color)
    search_label.configure(bg=bg_color, fg=fg_color)
    search_entry.configure(bg=entry_bg, fg=entry_fg, insertbackground=entry_fg, highlightbackground='#d9d9d9', highlightcolor='#a0a0a0', relief='sunken')
    for btn in [btn_prev, btn_play, btn_next, btn_load, darkmode_btn]:
        btn.configure(bg=btn_bg, fg=fg_color, activebackground=None)
    seed_frame.configure(bg=bg_color)

    seed_entry.configure(
        bg=entry_bg,
        fg=entry_fg,
        insertbackground=entry_fg,
        highlightbackground='#d9d9d9',
        highlightcolor='#a0a0a0',
        relief='sunken'
    )

    seed_apply_btn.configure(
        bg=btn_bg,
        fg=fg_color,
        activebackground=None
    )

def toggle_dark_mode():
    global dark_mode
    dark_mode = not dark_mode
    if dark_mode:
        apply_dark_mode()
    else:
        apply_light_mode()

bottom_btn_frame = tk.Frame(root, bg="#2e2e2e")
bottom_btn_frame.pack(pady=6)

btn_load = tk.Button(bottom_btn_frame, text="Load Folder", command=load_folder)
btn_load.pack(side="left", padx=6)

darkmode_btn = tk.Button(bottom_btn_frame, text='Toggle Dark Mode', command=toggle_dark_mode)
darkmode_btn.pack(side="left", padx=6)


apply_dark_mode()

###########################
# Hotkeys
###########################

VOLUME_STEP = 0.01
def volume_up():
    global volume
    volume = min(1.0, volume + VOLUME_STEP)
    pygame.mixer.music.set_volume(volume)
    volume_slider.set(volume)
    status_label.config(text=f"Volume: {int(volume*100)}%")
    root.after(1200, update_status_label)

def volume_down():
    global volume
    volume = max(0.0, volume - VOLUME_STEP)
    pygame.mixer.music.set_volume(volume)
    volume_slider.set(volume)
    status_label.config(text=f"Volume: {int(volume*100)}%")
    root.after(1200, update_status_label)

def toggle_pause():
    toggle_play()

if KEYBOARD_AVAILABLE:
    keyboard.add_hotkey('right ctrl+alt+up', volume_up)
    keyboard.add_hotkey('right ctrl+alt+down', volume_down)
    keyboard.add_hotkey('right ctrl+alt+pgdown', play_next)
    keyboard.add_hotkey('right ctrl+alt+pgup', play_prev)
    keyboard.add_hotkey('right ctrl+alt+l', toggle_pause)


###########################
# UI & Progress Updates
###########################

def update_ui_state():
    if paused:
        btn_play.config(text="▶ Resume")
    elif playing:
        btn_play.config(text="⏸ Pause")
    else:
        btn_play.config(text="▶ Play")

def update_status_label():
    if not playlist:
        status_label.config(text='No track loaded')
        return
    current = playlist[index]
    s = get_stats_for_path(current)
    status_label.config(text=f"{os.path.basename(current)} — Started: {s['started']} | Listened: {s['listened']} | Skipped: {s['skipped']}")

def update_progress():
    global seek_block_until, playback_offset, _listened_flag
    if playing:
        if not slider_dragging and time.time() > seek_block_until:
            pos_ms = pygame.mixer.music.get_pos()
            current_time = (pos_ms / 1000.0 if pos_ms >= 0 else 0.0) + playback_offset
            if track_duration > 0:
                frac = max(0.0, min(1.0, current_time / track_duration))
                progress_slider.set(frac)
            if track_duration > 0 and current_time >= track_duration - 0.5:
                if not _listened_flag:
                    increment_stat_for_path(playlist[index], 'listened')
                    _listened_flag = True
                play_next()
    update_status_label()
    root.after(250, update_progress)

update_progress()

###########################
# Scalable UI
###########################

def on_resize(event):
    width = root.winfo_width()
    scale = max(0.7, min(1.4, width / 560))

    playlist_box.config(font=("Segoe UI", int(10 * scale)))
    status_label.config(font=("Segoe UI", int(9 * scale)))
    volume_label.config(font=("Segoe UI", int(9 * scale)))
    search_label.config(font=("Segoe UI", int(9 * scale)))

    fixed_font = ("Segoe UI", 10)
    for widget in [btn_play, btn_prev, btn_next, btn_load, darkmode_btn]:
        widget.config(font=fixed_font)

    progress_slider.config(length=int(500 * scale))
    volume_slider.config(length=int(300 * scale))


root.bind("<Configure>", on_resize)

###########################
# Close
###########################

def _on_close():
    auto_stop_event.set()
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass
    save_stats()
    root.destroy()

root.protocol('WM_DELETE_WINDOW', _on_close)
root.mainloop()

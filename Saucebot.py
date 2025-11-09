#!/usr/bin/env python3
"""
SauceBot - touchscreen + GPIO control for two peristaltic pumps.
Controls:
 - Pump A (Tomato) on GPIO 17
 - Pump B (Mustard) on GPIO 27
Large touchscreen UI with counters and QR code.
"""

import json
import time
import threading
from pathlib import Path
from tkinter import Tk, Label, Button, Frame, messagebox, PhotoImage
import qrcode
from PIL import Image, ImageTk

# GPIO abstraction (gpiozero is pleasant)
from gpiozero import DigitalOutputDevice, Button as GPIOButton

# === CONFIG ===
PUMP_TOMATO_PIN = 17
PUMP_MUSTARD_PIN = 27
PHYSICAL_BUTTON_TOMATO_PIN = 5     # optional physical big button
PHYSICAL_BUTTON_MUSTARD_PIN = 6
STATS_FILE = Path("sauce_stats.json")
DEFAULT_DISPENSE_TIME_SECONDS = 1.5  # default single-press dispense time (calibrate)
MIN_INTERVAL_SECONDS = 1.5           # minimum seconds between dispenses per pump
MAX_DISPENSE_SECONDS = 6.0           # safety cap per dispense

# UI sizes (suitable for 7" touchscreen; adjust)
BIG_FONT = ("Helvetica", 48, "bold")
MED_FONT = ("Helvetica", 28)
SMALL_FONT = ("Helvetica", 18)

# === Hardware init ===
pump_tomato = DigitalOutputDevice(PUMP_TOMATO_PIN, active_high=True, initial_value=False)
pump_mustard = DigitalOutputDevice(PUMP_MUSTARD_PIN, active_high=True, initial_value=False)

# Optional physical buttons (pull-up)
try:
    phys_btn_tom = GPIOButton(PHYSICAL_BUTTON_TOMATO_PIN, pull_up=True, bounce_time=0.05)
    phys_btn_mus = GPIOButton(PHYSICAL_BUTTON_MUSTARD_PIN, pull_up=True, bounce_time=0.05)
except Exception:
    phys_btn_tom = phys_btn_mus = None

# === State ===
state = {
    "served": 0,
    "tomato_served": 0,
    "mustard_served": 0,
    "last_dispense_time": 0.0
}

# Load/save
def load_stats():
    if STATS_FILE.exists():
        try:
            j = json.loads(STATS_FILE.read_text())
            state.update(j)
        except Exception:
            pass

def save_stats():
    STATS_FILE.write_text(json.dumps({
        "served": state["served"],
        "tomato_served": state["tomato_served"],
        "mustard_served": state["mustard_served"],
        "last_dispense_time": state["last_dispense_time"]
    }))

# Dispense helper with safety checks
dispense_lock = threading.Lock()

def dispense(pump_device, seconds):
    """Run pump for `seconds` (non-blocking)."""
    seconds = max(0.05, min(seconds, MAX_DISPENSE_SECONDS))
    def worker():
        with dispense_lock:
            pump_device.on()
            time.sleep(seconds)
            pump_device.off()
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t

# UI & logic
class SauceBotUI:
    def __init__(self, root):
        self.root = root
        root.title("SauceBot")
        root.attributes("-fullscreen", True)
        root.configure(bg="black")

        # Top counter
        self.counter_label = Label(root, text=self.counter_text(), font=BIG_FONT, fg="white", bg="black")
        self.counter_label.pack(pady=20)

        # Buttons frame
        frm = Frame(root, bg="black")
        frm.pack(expand=True, fill="both", padx=20, pady=10)

        self.btn_tomato = Button(frm, text="Tomato\n(Press)", font=BIG_FONT, width=12, height=3, bg="#c62828", fg="white", command=self.on_tomato)
        self.btn_mustard = Button(frm, text="Mustard\n(Press)", font=BIG_FONT, width=12, height=3, bg="#f9a825", fg="black", command=self.on_mustard)
        self.btn_both = Button(frm, text="Both\n(Press)", font=BIG_FONT, width=12, height=3, bg="#6a1b9a", fg="white", command=self.on_both)

        # Layout large buttons horizontally
        self.btn_tomato.grid = self.btn_tomato
        self.btn_tomato.pack(in_=frm, side="left", expand=True, padx=10, pady=10)
        self.btn_mustard.pack(in_=frm, side="left", expand=True, padx=10, pady=10)
        self.btn_both.pack(in_=frm, side="left", expand=True, padx=10, pady=10)

        # Bottom controls: QR generation and reset (reset behind long press)
        bottom = Frame(root, bg="black")
        bottom.pack(side="bottom", fill="x", pady=12)
        self.qr_btn = Button(bottom, text="Show QR", font=MED_FONT, width=12, height=2, command=self.show_qr)
        self.qr_btn.pack(side="left", padx=12)
        self.close_btn = Button(bottom, text="Exit (admin)", font=SMALL_FONT, width=12, height=1, command=self.try_exit)
        self.close_btn.pack(side="right", padx=12)

        # Keep updating counter periodically
        self.update_ui()
        load_stats()

        # Hook physical buttons
        if phys_btn_tom:
            phys_btn_tom.when_pressed = lambda: self.on_tomato(from_physical=True)
        if phys_btn_mus:
            phys_btn_mus.when_pressed = lambda: self.on_mustard(from_physical=True)

    def counter_text(self):
        return f"Sausages served: {state['served']}"

    def update_ui(self):
        self.counter_label.config(text=self.counter_text())
        # schedule next update
        self.root.after(500, self.update_ui)

    def too_soon(self):
        now = time.time()
        if now - state["last_dispense_time"] < MIN_INTERVAL_SECONDS:
            return True
        return False

    def record_served(self, which):
        state["served"] += 1
        if which == "tomato":
            state["tomato_served"] += 1
        elif which == "mustard":
            state["mustard_served"] += 1
        state["last_dispense_time"] = time.time()
        save_stats()

    def on_tomato(self, from_physical=False):
        if self.too_soon():
            return
        # dispense preset time (calibrate)
        dispense(pump_tomato, DEFAULT_DISPENSE_TIME_SECONDS)
        self.record_served("tomato")

    def on_mustard(self, from_physical=False):
        if self.too_soon():
            return
        dispense(pump_mustard, DEFAULT_DISPENSE_TIME_SECONDS)
        self.record_served("mustard")

    def on_both(self):
        if self.too_soon():
            return
        # run both pumps simultaneously for same time
        dispense(pump_tomato, DEFAULT_DISPENSE_TIME_SECONDS)
        dispense(pump_mustard, DEFAULT_DISPENSE_TIME_SECONDS)
        self.record_served("tomato")
        self.record_served("mustard")

    def show_qr(self):
        # Make QR coding the current stats as a JSON string or URL
        txt = json.dumps({
            "served": state["served"],
            "tomato": state["tomato_served"],
            "mustard": state["mustard_served"],
            "timestamp": int(time.time())
        })
        qr = qrcode.make(txt).resize((400, 400))
        qr_path = Path("stats_qr.png")
        qr.save(qr_path)
        # Display in a popup
        img = ImageTk.PhotoImage(qr)
        top = Tk()
        top.title("SauceBot QR")
        top.geometry("420x460")
        lbl = Label(top, image=img)
        lbl.image = img
        lbl.pack(padx=10, pady=10)
        Label(top, text="Scan to view counts", font=SMALL_FONT).pack()
        # Keep this window independent
        top.mainloop()

    def try_exit(self):
        # simple admin exit with a confirmation
        if messagebox.askyesno("Exit", "Exit SauceBot app?"):
            self.root.destroy()

def main():
    load_stats()
    root = Tk()
    app = SauceBotUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import asyncio
import json
import os.path
import sys
import tkinter as tk
import tkinter.filedialog
import tkinter.messagebox
from tkinter import ttk
from typing import Sequence, Tuple

from get_brstm import SongVariantURL, TitledSongInfo, get_brstms
from loop import PlaytimeUpdate
from loopaudio import SongLoop, open_loops


class UpdaterProgressBar(PlaytimeUpdate):

    def __init__(self, song: SongLoop, progressbar: ttk.Progressbar):
        super().__init__(song)
        self.bar = progressbar

    def start(self):
        self.val = 0
        self.bar["value"] = 0

    def update(self):
        progress = int(self.song.position / len(self.song)
                       * self.bar["maximum"])
        if progress != self.val:
            self.bar["value"] = progress
            self.val = progress


class LoopGUI:

    def __init__(self, master: tk.Tk):
        self.master = master
        master.title("VGM Looper")

        # Input file and play controls
        self._build_input_panel(master, 0)

        # Now playing
        play_panel = tk.LabelFrame(master, text="Now playing")

        self.now_playing = tk.StringVar(value="")
        tk.Label(play_panel, textvariable=self.now_playing).grid(row=0, sticky="W")
        self.song_progress = tk.IntVar()
        self.progress_bar = ttk.Progressbar(play_panel, mode="determinate")
        self.progress_bar.grid(row=1, sticky="EW")

        play_panel.columnconfigure(0, weight=1)
        play_panel.grid(row=1, columnspan=2, sticky="EW")

        self._build_variants_layers(master, 2)

        # BRSTM downloader
        def open_importer():
            tkinter.messagebox.showerror('Not implemented', 'SmashCustomMusic import GUI not yet working')
            # new_window = tk.Toplevel(self.master)
            # SCMImportGUI(new_window)
        ttk.Button(master, text="Import files from SmashCustomMusic archive...",
                   command=open_importer).grid(row=5, columnspan=2, sticky="SE")

        master.rowconfigure(2, weight=1)
        master.columnconfigure(0, weight=1, uniform='a')
        master.columnconfigure(1, weight=1, uniform='a')

        master.configure(padx=8, pady=5)

    def _build_input_panel(self, master, row):
        file_pane = tk.LabelFrame(master, text="File")

        self.input_filename = tk.StringVar(file_pane)

        def select_file():
            self.input_filename.set(
                tkinter.filedialog.askopenfilename(
                    initialdir=sys.path[0],
                    defaultextension="json",
                    filetypes=[("JSON files", "json")]
                )
            )
        ttk.Button(file_pane, text="Pick file",
                   command=select_file).grid(row=0, column=0)

        ttk.Entry(file_pane,
                  textvariable=self.input_filename).grid(row=0, column=1, sticky="EW")

        ttk.Button(file_pane, text="Load",
                   command=self.load).grid(row=0, column=2)

        self.stop_button = ttk.Button(
            file_pane, text="Stop", command=self.stop_loop)
        self.stop_button.state(["disabled"])
        self.stop_button.grid(row=0, column=3)

        canvas = tk.Canvas(file_pane, height=0, bd=0, highlightthickness=0, relief="ridge")
        scrollbar = ttk.Scrollbar(file_pane, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=scrollbar.set, yscrollcommand=scrollbar.set)
        canvas.bind("<Configure>", lambda _: canvas.configure(
            scrollregion=canvas.bbox('all')))
        canvas.grid(row=1, columnspan=4, sticky="EW")
        scrollbar.grid(row=2, columnspan=4, sticky="EW")

        self.song_panel = tk.Frame(canvas)
        canvas.create_window((0, 0), window=self.song_panel, anchor='nw')

        file_pane.columnconfigure(1, weight=1)
        file_pane.grid(row=row, columnspan=2, sticky="NEW")

    def _build_variants_layers(self, master, row):
        # Variants
        self.variant_pane = tk.LabelFrame(master, text="Variants")
        self.variant_pane.grid(row=row, column=0, sticky="NESW")

        # Layers
        self.layer_pane = tk.LabelFrame(master, text="Layers")
        self.layer_pane.grid(row=row, column=1, sticky="NESW")

    def load(self):
        input_file = self.input_filename.get()

        def play_song(song: SongLoop):
            return lambda: self.play_loop(song)
        
        for widget in self.song_panel.winfo_children():
            widget.destroy()

        self.songs = []
        for song in open_loops(input_file, lambda file, *_: tkinter.messagebox.showerror(
                "Could not open file", f"File '{file}' does not exist")):
            song_record = {
                "name": song.name,
                "button": ttk.Button(
                    master=self.song_panel,
                    text=song.name,
                    command=play_song(song)
                )
            }
            self.songs.append(song_record)
            song_record["button"].pack(side=tk.LEFT)
            self.song_panel.pack()

    def play_loop(self, song: SongLoop):
        try:
            try:
                self.song.stop()
            except AttributeError:
                pass
            finally:
                self.song = song
                pb = UpdaterProgressBar(song, self.progress_bar)
                pb.start()
                song.play_async(callback=pb.update)
            self.stop_button.state(["!disabled"])

            for widget in self.variant_pane.winfo_children():
                widget.destroy()
            selected_variant = tk.IntVar(master=self.variant_pane, value=0)
            variants = list(song.variants())

            def select_variant():
                song.set_variant(variants[selected_variant.get()], 5.0)

            radiobuttons = [ttk.Radiobutton(
                                self.variant_pane,
                                variable=selected_variant,
                                text=var, value=pos,
                                command=select_variant)
                            for pos, var in enumerate(variants)]
            for button in radiobuttons:
                button.pack(anchor=tk.W)
            if radiobuttons[0]["text"] == "":
                radiobuttons[0]["text"] = "<default>"
            selected_variant.set(0)

            for widget in self.layer_pane.winfo_children():
                widget.destroy()

            def layer_set_function(layer, variable):
                return lambda: song.set_layer(layer, variable.get())

            for lay in song.layers():
                var = tk.IntVar()
                check = ttk.Checkbutton(
                    self.layer_pane, variable=var, text=lay, command=layer_set_function(lay, var))
                var.set(0)
                check.pack(anchor=tk.W)

            self.now_playing.set(song.title)

        except FileNotFoundError as err:
            tkinter.messagebox.showinfo(
                title=None, message="File doesn't exist: " + err.filename)

    def stop_loop(self):
        self.song.stop()
        self.stop_button.state(["disabled"])
        self.now_playing.set("")
        self.progress_bar["value"] = 0


class SCMImportGUI:

    def __init__(self, master: tk.Tk):
        master.title("SmashCustomMusic import")

        self._build_file_panel(master)

        self.variant_sets = []
        self.set_ui = ttk.Notebook(master)
        self.set_ui.grid(row=1, sticky="NSEW")

        manage = tk.Frame(self.set_ui)
        tk.Label(
            manage,
            text="Variant sets make up their own loops. Each has its own variants and layers."
        ).pack(side="top")
        self.add_set_button = ttk.Button(manage, text="Add variant set", command=self.add_set)
        self.add_set_button.pack(side="top")
        self.remove_set_button = ttk.Button(
            manage, default="disabled",
            text="Remove variant set",
            command=self.remove_set
        )
        self.remove_set_button.pack(side="top")
        manage.grid(row=0)
        self.set_ui.add(manage, text="Manage variant sets")
        self.add_set()
        self.set_ui.select(1)

        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)
        master.configure(padx=8, pady=5)

    def _build_file_panel(self, master):
        file_panel = tk.LabelFrame(master, text="File")

        file_field = tk.Frame(file_panel)
        self.file_name = tk.StringVar(file_field)
        tk.Label(file_field, text="File name").grid(row=0, column=0)
        tk.Entry(file_field, textvariable=self.file_name).grid(
            row=0, column=1, sticky="EW")
        ttk.Button(file_field, text="Select", command=lambda: self.file_name.set(
            tkinter.filedialog.asksaveasfilename(
                initialdir=sys.path[0],
                confirmoverwrite=True,
                filetypes=[("JSON file", "json")]
            ))
        ).grid(row=0, column=2)
        file_field.columnconfigure(1, weight=1)
        file_field.grid(row=0, sticky="EW")

        ttk.Button(file_panel, text="Start conversion",
                   command=self.start_conversion).grid(row=2, sticky="E")

        file_panel.columnconfigure(0, weight=1)
        file_panel.grid(row=0, sticky="NSEW")

    def start_conversion(self):
        file = get_brstms(
            os.path.splitext(self.file_name.get())[0],
            [varset.create_song_info() for varset in self.variant_sets],
            None,
            lambda e, file: tkinter.messagebox.showerror(
                "Download error", "Could not download file: " + file + "\n" + e)
        )
        json.dump(
            file,
            open(self.file_name.get(), "wt")
        )
        tkinter.messagebox.showinfo(message="Loop created!")
    
    def add_set(self):
        setui = VariantSetUI(self.set_ui, row=0, nb=self.set_ui, index=len(self.variant_sets))
        self.variant_sets.append(setui)
        self.set_ui.add(setui.panel, text="<untitled>")
        self.remove_set_button.state(
            ["!disabled"] if len(self.variant_sets) > 1 else ["disabled"])
    
    def remove_set(self):
        setui = self.variant_sets[-1]
        self.variant_sets.pop()
        setui.panel.destroy()
        self.remove_set_button.state(["!disabled"] if len(
            self.variant_sets) > 1 else ["disabled"])


class VariantSetUI:

    def __init__(self, master, row, nb: ttk.Notebook, index: int):
        self.panel = tk.Frame(master)

        name_panel = tk.LabelFrame(self.panel, text="Information")
        self.title = tk.StringVar(self.panel)
        tk.Label(name_panel, text="Title:").grid(row=0, column=0)
        tk.Entry(name_panel, textvariable=self.title).grid(
            row=0, column=1, sticky="EW")
        name_panel.columnconfigure(1, weight=1)
        name_panel.grid(row=0, sticky="EW")

        def set_widget_name(*_):
            nb.tab(index + 1, text = self.short_name.get() or "<untitled>")

        self.short_name = tk.StringVar(self.panel)
        tk.Label(name_panel, text="Short name:").grid(row=1, column=0)
        name_entry = tk.Entry(name_panel, textvariable=self.short_name)
        name_entry.bind("<FocusOut>", set_widget_name)
        name_entry.grid(row=1, column=1, sticky="EW")
        name_panel.columnconfigure(1, weight=1)

        self.variant_panel = tk.LabelFrame(self.panel, text="Variants")
        self.variants = []
        tk.Label(
                self.variant_panel,
                text="Different versions of the same song. Only one plays at at time."
            ).grid(
            row=0, columnspan=2)
        tk.Label(self.variant_panel, text="Variant name").grid(
            row=1, column=0, sticky="W")
        tk.Label(self.variant_panel, text="BRSTM page").grid(
            row=1, column=1, sticky="W")
        add_var_button = ttk.Button(
            self.variant_panel,
            command=lambda: self.push_field(
                self.variant_panel, self.variants, add_var_button, remove_var_button, 1),
            text="+")
        remove_var_button = ttk.Button(
            self.variant_panel,
            command=lambda: self.pop_field(
                self.variants, add_var_button, remove_var_button, 1),
            text="-")
        self.push_field(
            self.variant_panel, self.variants, add_var_button, remove_var_button, 1)

        self.variant_panel.columnconfigure(0, weight=1)
        self.variant_panel.columnconfigure(1, weight=1)
        self.variant_panel.grid(row=2, sticky="NSEW")

        self.layer_panel = tk.LabelFrame(self.panel, text="Layers")
        self.layers = []
        tk.Label(
            self.layer_panel,
            text="Any combination of layers may play over the selected variant."
        ).grid(row=0, columnspan=2)
        tk.Label(self.layer_panel, text="Layer name").grid(
            row=1, column=0, sticky="W")
        tk.Label(self.layer_panel, text="BRSTM page").grid(
            row=1, column=1, sticky="W")
        add_lay_button = ttk.Button(
            self.layer_panel,
            command=lambda: self.push_field(
                self.layer_panel, self.layers, add_lay_button, remove_lay_button, 0),
            text="+")
        remove_lay_button = ttk.Button(
            self.layer_panel,
            command=lambda: self.pop_field(
                self.layers, add_lay_button, remove_lay_button, 0),
            text="-")
        self.grid_buttons(add_lay_button, remove_lay_button, 0, 0)

        self.layer_panel.columnconfigure(0, weight=1)
        self.layer_panel.columnconfigure(1, weight=1)
        self.layer_panel.grid(row=3, sticky="NSEW")

        self.panel.rowconfigure(2, weight=1)
        self.panel.rowconfigure(3, weight=1)
        self.panel.columnconfigure(0, weight=1)
        self.panel.grid(row=row, sticky="NSEW")
    
    def grid_buttons(self, add, remove, row, requirement):
        add.grid(
            row=row + 2, column=0, sticky="EW")
        remove.grid(
            row=row + 2, column=1, sticky="EW")
        remove.state(
            ["disabled" if row <= requirement else "!disabled"])

    def push_field(self,
                   panel: tk.PanedWindow,
                   rowdata: Sequence[tuple],
                   addbutton: ttk.Button,
                   removebutton: ttk.Button,
                   requirement: int
                  ):
        name = tk.StringVar(panel)
        url = tk.StringVar(panel)
        nfield = tk.Entry(panel, textvariable=name)
        nfield.grid(row=len(rowdata) + 2, column=0, sticky="EW")
        ufield = tk.Entry(panel, textvariable=url)
        ufield.grid(row=len(rowdata) + 2, column=1, sticky="EW")
        rowdata.append((name, url, nfield, ufield))

        self.grid_buttons(addbutton, removebutton, len(rowdata), requirement)

    def pop_field(self,
                  rowdata: Sequence[tuple],
                  addbutton: ttk.Button,
                  removebutton: ttk.Button,
                  requirement: int
                 ):
        item = rowdata.pop()
        self.grid_buttons(addbutton, removebutton, len(rowdata), requirement)
        for i in item[2:4]:
            i.destroy()
    
    def get_short_name(self) -> str:
        return self.short_name.get()
    
    def get_title(self) -> str:
        return self.title.get()
    
    def get_variants(self) -> Sequence[Tuple]:
        return [(var[0].get(), var[1].get()) for var in self.variants]
    
    def get_layers(self) -> Sequence[Tuple]:
        return [(lay[0].get(), lay[1].get()) for lay in self.layers]
    
    def create_song_info(self) -> TitledSongInfo:
        return TitledSongInfo(
            self.short_name.get(),
            self.title.get(),
            [SongVariantURL("-" + var[0] if var[0] else "", var[1]) for var in self.get_variants()],
            [SongVariantURL("-" + lay[0], lay[1]) for lay in self.get_layers()]
        )


def main():
    window = tk.Tk()
    LoopGUI(window)
    window.mainloop()


if __name__ == "__main__":
    main()

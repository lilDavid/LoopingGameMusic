import sys
import tkinter as tk
import tkinter.filedialog
import tkinter.messagebox
import traceback
from tkinter import ttk
from typing import Sequence, Sized, Tuple

import loopaudio as la
from get_brstm import Metadata, SongInfo, SongVariantURL, create_song


class UpdaterProgressBar():

    def __init__(self, song: la.SongLoop, progressbar: ttk.Progressbar):
        self.song = song
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
        tk.Label(play_panel, textvariable=self.now_playing).grid(row=0, sticky="EW")
        self.song_progress = tk.IntVar()
        self.progress_bar = ttk.Progressbar(play_panel, mode="determinate")
        self.progress_bar.grid(row=1, sticky="EW")

        play_panel.columnconfigure(0, weight=1)
        play_panel.grid(row=1, columnspan=2, sticky="EW")

        self._build_variants_layers(master, 2)

        # Volume
        volume_panel = tk.Frame(master)
        
        self.pause_text = tk.StringVar(value='Pause')
        def toggle_pause():
            la.paused = not la.paused
            self.pause_text.set(('Pause', 'Play')[la.paused])
        ttk.Button(
            volume_panel,
            textvariable=self.pause_text,
            command=toggle_pause
        ).grid(row=0, column=0)

        volpercent = tk.StringVar()
        def set_volume(vol):
            vol = float(vol)
            la.volume = vol
            volpercent.set(f'Volume: {vol:3.0%}')
        set_volume(la.volume)
        
        tk.Label(
            volume_panel,
            textvariable=volpercent
        ).grid(row=0, column=1, sticky='E')

        ttk.Scale(
            volume_panel,
            from_=0,
            to=1.0,
            value=1.0,
            orient='horizontal',
            command=set_volume
        ).grid(row=0, column=2, sticky='EW')
        volume_panel.columnconfigure(2, weight=1)
        volume_panel.grid(row=5, columnspan=2, sticky='EW')

        # BRSTM downloader
        def open_importer():
            new_window = tk.Toplevel(self.master)
            SCMImportGUI(new_window)
        ttk.Button(master, text="Import files from SmashCustomMusic archive...",
                   command=open_importer).grid(row=6, columnspan=2, sticky="SE")

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

        tk.Entry(file_pane,
                  textvariable=self.input_filename).grid(row=0, column=1, sticky="EW")

        ttk.Button(file_pane, text="Load",
                   command=self.load).grid(row=0, column=2)

        # List of parts
        canvas = tk.Canvas(file_pane, height=0, bd=0, highlightthickness=0, relief="ridge")
        scrollbar = ttk.Scrollbar(file_pane, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=scrollbar.set, yscrollcommand=scrollbar.set)
        canvas.bind("<Configure>", lambda _: canvas.configure(
            scrollregion=canvas.bbox('all')))
        canvas.grid(row=1, columnspan=3, sticky="EW")
        scrollbar.grid(row=2, columnspan=3, sticky="EW")

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

        def play_song(song: la.SongLoop):
            return lambda: self.play_loop(song)
        
        # Rebuild song panel

        for widget in self.song_panel.winfo_children():
            widget.destroy()

        self.songs = []
        loops = la.open_loops(
            input_file,
            lambda file, *_: tkinter.messagebox.showerror(
                "Could not open file", f"File '{file}' does not exist"
            )
        )
        for num, song in enumerate(loops, start=1):
            song_record = {
                "name": song.name,
                "button": ttk.Button(
                    master=self.song_panel,
                    text=(song.name
                        or ('Play' if len(loops) == 1
                        else f'Part {num}')),
                    command=play_song(song)
                )
            }
            self.songs.append(song_record)
            song_record["button"].pack(side=tk.LEFT)
            self.song_panel.pack()

        self.stop_button = ttk.Button(
            self.song_panel, text="Stop", command=self.stop_loop)
        self.stop_button.state(["disabled"])
        self.stop_button.pack(side=tk.LEFT)

    def play_loop(self, song: la.SongLoop):
        # Stop song and change parts
        la.paused = False
        self.pause_text.set('Pause')
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

        # Rebuild variant and layer panels

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
        
        # Reset variants/layers for next part
        if song.variants():
            song.set_variant(next(iter(song.variants())))
        song.set_layers(0)

        self.now_playing.set('\n'.join(song.tags.to_str_list()))

    def stop_loop(self):
        self.song.stop()
        self.stop_button.state(["disabled"])
        self.now_playing.set("")
        self.progress_bar["value"] = 0
        for widget in self.variant_pane.winfo_children():
            widget.destroy()
        for widget in self.layer_pane.winfo_children():
            widget.destroy()


class SCMImportGUI:

    def __init__(self, master: tk.Tk):
        master.title("SmashCustomMusic import")
        self.build_file_panel(master)
        self.initialize_parts(master)
        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)
        master.configure(padx=8, pady=5)

    def initialize_parts(self, master):
        self.parts = []
        self.create_part_panel(master)
        self.add_part()
        self.part_ui.select(1)

    def create_part_panel(self, master):
        self.part_ui = ttk.Notebook(master)
        self.part_ui.grid(row=1, sticky="NSEW")
        manage = self.create_part_management()
        self.part_ui.add(manage, text="Manage parts")

    def create_part_management(self):
        manage = tk.Frame(self.part_ui)
        tk.Label(
            manage,
            text="Each part is a separate loop with its own variants and layers."
        ).pack(side="top")

        self.add_part_button = self.create_part_button(
            manage,
            text="Add new part",
            command=self.add_part
        )
        self.remove_part_button = self.create_part_button(
            manage,
            default="disabled",
            text="Remove last part",
            command=self.remove_part
        )

        manage.grid(row=0)
        return manage
    
    def create_part_button(self, *args, **kwargs):
        button = ttk.Button(*args, **kwargs)
        button.pack(side='top')
        return button

    def build_file_panel(self, master):
        file_panel = tk.LabelFrame(master, text="File")
        self.create_file_selector(file_panel)
        self.create_conversion_start(file_panel)
        file_panel.columnconfigure(0, weight=1)
        file_panel.grid(row=0, sticky="NSEW")

    def create_conversion_start(self, master):
        conversion_start = tk.Frame(master)
        self.create_use_json_check(conversion_start)
        self.create_start_button(conversion_start)
        conversion_start.columnconfigure(0, weight=1)
        conversion_start.grid(row=1, sticky="EW")

    def create_start_button(self, master):
        ttk.Button(
            master,
            text="Start conversion",
            command=self.start_conversion
        ).grid(row=0, column=1, sticky='E')

    def create_use_json_check(self, master):
        self.use_json = tk.BooleanVar(master)
        json_btn = ttk.Checkbutton(
            master,
            text='Use JSON',
            offvalue=False,
            onvalue=True,
            variable=self.use_json
        )
        json_btn.grid(row=0, column=0, sticky='W', padx=5)
        self.use_json.set(True)

    def create_file_selector(self, master):
        file_field = tk.Frame(master)
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

    def start_conversion(self):
        try:
            create_song(
                self.file_name.get(),
                [part.create_song_info() for part in self.parts]
            )
        except Exception as exc:
            err = f'Could not create song files:\n{exc}'
            traceback.print_exception(None, exc, exc.__traceback__)
            tkinter.messagebox.showerror(message=err)
        else:
            tkinter.messagebox.showinfo(message="Loop created!")
    
    def add_part(self):
        partui = SongPartUI(
            self.part_ui,
            row=0,
            nb=self.part_ui,
            index=len(self.parts)
        )
        self.parts.append(partui)
        self.part_ui.add(partui.panel, text="<untitled>")
        disable_for_size(self.remove_part_button, self.parts, 1)
    
    def remove_part(self):
        partui = self.parts.pop()
        partui.panel.destroy()
        disable_for_size(self.remove_part_button, self.parts, 1)


def disable_for_size(button: ttk.Button, collection: Sized, minsize: int):
    state = '!' if len(collection) > minsize else ''
    button.state([f'{state}disabled'])


class SongPartMetadata:
    def __init__(self, master):
        self.master = master

        self.title = tk.StringVar(master)
        self.artists = []
        self.album = tk.StringVar(master)
        self.number = tk.StringVar(master)
        self.year = tk.StringVar(master)
        self.games = []
    
    def to_get_brstm_meta(self):
        return Metadata(
            title=self.title.get(),
            artist=[a.get() for a in self.artists],
            album=self.album.get(),
            track_number=self.number.get(),
            year=self.year.get(),
            game=[g.get() for g in self.games]
        )


def create_window(master, title):
    window = tk.Toplevel(master)
    window.title(title)
    return window


def create_field(master, label, variable, row):
    tk.Label(master, text=label).grid(row=row, column=0)
    entry = tk.Entry(master, textvariable=variable)
    entry.grid(row=row, column=1, sticky='EW')
    return entry


class EditableListEntry:
    def __init__(self, master, sequence):
        self.frame = tk.Frame(master)
        self.sequence = sequence

        for i, var in enumerate(sequence):
            self.add_field_entry(i, var)
        self.create_field_buttons()
        self.grid_field_buttons()
        
    def add_field_entry(self, row, var):
        entry = tk.Entry(self.frame, textvariable=var)
        entry.grid(row=row, columnspan=2, sticky='EW')
    
    def create_field_buttons(self):
        self.add_button = ttk.Button(
            self.frame,
            text='+',
            command=self.add_field
        )
        self.remove_button = ttk.Button(
            self.frame,
            text='-',
            command=self.remove_field
        )
    
    def grid_field_buttons(self):
        self.add_button.grid(row=len(self.sequence), column=0)
        self.remove_button.grid(row=len(self.sequence), column=1)
        disable_for_size(self.remove_button, self.sequence, 0)
        
    def add_field(self):
        var = tk.StringVar(self.frame)
        self.add_field_entry(len(self.sequence), var)
        self.sequence.append(var)
        self.grid_field_buttons()
    
    def remove_field(self):
        entries = self.frame.grid_slaves(row=len(self.sequence) - 1)
        self.sequence.pop()
        for entry in entries:
            entry.destroy()
        self.grid_field_buttons()


def create_multi_field(master, label, sequence, row):
    tk.Label(master, text=label).grid(row=row, column=0, sticky='N')
    EditableListEntry(master, sequence
        ).frame.grid(row=row, column=1, sticky='NSEW')


class SongPartUI:

    def __init__(self, master, row, nb: ttk.Notebook, index: int):
        self.panel = tk.Frame(master)

        self.create_description_panel(nb, index)
        self.variant_panel, self.variants = self.create_track_panel(
            label='Variant',
            description=('Different versions of the same song. '
                + 'Only one plays at at time.'),
            row=3,
            minlength=1
        )
        self.layer_panel, self.layers = self.create_track_panel(
            label='Layer',
            description=('Any combination of layers may play'
                + 'over the selected variant.'),
            row=4,
            minlength=0
        )

        self.panel.rowconfigure(3, weight=1)
        self.panel.rowconfigure(4, weight=1)
        self.panel.columnconfigure(0, weight=1)
        self.panel.grid(row=row, sticky="NSEW")

    def create_description_panel(self, nb, index):
        name_panel = tk.LabelFrame(self.panel, text="Information")
        self.metadata = SongPartMetadata(name_panel)
        create_field(name_panel, 'Title:', self.metadata.title, 0)
        self.create_part_name_entry(nb, index, name_panel)
        self.create_filename_field(name_panel)
        self.create_metadata_button(name_panel)
        name_panel.columnconfigure(1, weight=1)
        name_panel.grid(row=0, sticky="EW")
    
    def create_part_name_entry(self, nb, index, master):
        def set_widget_name(*_):
            nb.tab(index + 1, text=self.part_name.get() or "<untitled>")

        self.part_name = tk.StringVar(self.panel)
        name_entry = create_field(
            master,
            'Part name:',
            self.part_name,
            1
        )
        name_entry.bind("<FocusOut>", set_widget_name)
    
    def create_filename_field(self, master):
        self.filename = tk.StringVar(self.panel)
        create_field(master, 'Filename:', self.filename, 2)
    
    def create_metadata_button(self, master):
        button = ttk.Button(
            master,
            command=lambda: self.create_metadata_dialog(master),
            text='Other metadata...'
        )
        button.grid(row=3, column=0, columnspan=2, sticky='E')
    
    def create_metadata_dialog(self, master):
        window = create_window(master, 'Song metadata')
        self.create_metadata_fields(window)
    
    def create_metadata_fields(self, master):
        create_field(master, 'Title:', self.metadata.title, 0)
        create_multi_field(master, 'Artist:', self.metadata.artists, 1)
        create_field(master, 'Album:', self.metadata.album, 2)
        create_field(master, 'Track number:', self.metadata.number, 3)
        create_field(master, 'Year:', self.metadata.year, 4)
        create_multi_field(master, 'Game:', self.metadata.games, 5)

    def create_track_panel(
        self,
        label,
        description,
        row,
        minlength
    ):
        panel = tk.LabelFrame(self.panel, text=f'{label}s')
        tracks = []

        tk.Label(panel, text=description).grid(row=0, columnspan=2)
        self.create_table_header(label, panel)
        add_button, remove_button = self.create_track_buttons(minlength, panel, tracks)
        self.grid_buttons(add_button, remove_button, tracks, minlength)
        for _ in range(minlength):
            self.push_field(panel, tracks, add_button, remove_button, minlength)

        panel.columnconfigure(0, weight=1)
        panel.columnconfigure(1, weight=1)
        panel.grid(row=row, sticky="NSEW")

        return panel, tracks

    def create_table_header(self, label, panel):
        tk.Label(panel, text=f'{label} name').grid(
            row=1, column=0, sticky="W")
        tk.Label(panel, text="BRSTM page").grid(
            row=1, column=1, sticky="W")

    def create_track_buttons(self, minlength, panel, tracks):
        add_button = ttk.Button(
            panel,
            command=lambda: self.push_field(
                panel, tracks, add_button, remove_button, minlength),
            text="+")
        remove_button = ttk.Button(
            panel,
            command=lambda: self.pop_field(
                tracks, add_button, remove_button, minlength),
            text="-")
            
        return add_button, remove_button
    
    def grid_buttons(self, add, remove, collection, minsize):
        row = len(collection) + 2
        add.grid(row=row, column=0, sticky="EW")
        remove.grid(row=row, column=1, sticky="EW")
        disable_for_size(remove, collection, minsize)

    def push_field(self,
                   panel: tk.PanedWindow,
                   rowdata: Sequence[tuple],
                   addbutton: ttk.Button,
                   removebutton: ttk.Button,
                   minsize: int
                  ):
        name = tk.StringVar(panel)
        url = tk.StringVar(panel)
        row = len(rowdata) + 2
        nfield = self.create_track_entry(panel, name, row, 0)
        ufield = self.create_track_entry(panel, url, row, 1)
        rowdata.append((name, url, nfield, ufield))

        self.grid_buttons(addbutton, removebutton, rowdata, minsize)
    
    def create_track_entry(self, master, variable, row, column):
        entry = tk.Entry(master, textvariable=variable)
        entry.grid(row=row, column=column, sticky="EW")
        return entry

    def pop_field(self,
                  rowdata: Sequence[tuple],
                  addbutton: ttk.Button,
                  removebutton: ttk.Button,
                  requirement: int
                 ):
        item = rowdata.pop()
        self.grid_buttons(addbutton, removebutton, rowdata, requirement)
        for i in item[2:4]:
            i.destroy()
    
    def get_part_name(self) -> str:
        return self.part_name.get()

    def get_title(self) -> str:
        return self.metadata.title
    
    def get_variants(self) -> Sequence[Tuple]:
        return [(var[0].get(), var[1].get()) for var in self.variants]
    
    def get_layers(self) -> Sequence[Tuple]:
        return [(lay[0].get(), lay[1].get()) for lay in self.layers]
    
    def create_song_info(self) -> SongInfo:
        return SongInfo(
            self.part_name.get(),
            self.filename.get(),
            self.metadata.to_get_brstm_meta(),
            [SongVariantURL(var[0], var[1]) for var in self.get_variants()],
            [SongVariantURL(lay[0], lay[1]) for lay in self.get_layers()]
        )


def main():
    window = tk.Tk()
    LoopGUI(window)
    window.mainloop()


if __name__ == "__main__":
    main()

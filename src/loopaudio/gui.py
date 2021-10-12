import itertools
import sys
import tkinter as tk
import tkinter.filedialog
import tkinter.messagebox
import traceback
from tkinter import ttk
from typing import NamedTuple, Sequence, Sized, Tuple

import loopaudio as la
from loopaudio.convert import (Metadata, SongPart, SongTrackURL, create_song,
                               create_song_audio_only)


TTK_ENABLED = '!disabled'


class SongProgressUpdater:

    def __init__(self, song: la.SongPart, progressbar: ttk.Progressbar):
        self.song = song
        self.bar = progressbar

    def start(self):
        self.val = 0
        self.bar["value"] = 0

    def update(self):
        progress = int(self.song.position / len(self.song) * self.bar["maximum"])
        if progress != self.val:
            self.bar["value"] = progress
            self.val = progress


class LoopGUI:

    def __init__(self, master: tk.Tk, preloaded_song: str = None):
        self.configure_master(master)
        self.preload_file(preloaded_song)

    def configure_master(self, master: tk.Tk):
        master.title("VGM Looper")

        self.create_input_panel(master, 0)
        self.create_now_playing_panel(master, 1)
        self.create_variant_layer_panel(master, 2)
        self.create_volume_panel(master, 3)
        self.create_import_button(master, 4)

        master.rowconfigure(2, weight=1)
        master.columnconfigure(0, weight=1, uniform='a')
        master.columnconfigure(1, weight=1, uniform='a')

        master.configure(padx=8, pady=5)

    def preload_file(self, preloaded_song: str):
        if preloaded_song is not None:
            self.input_filename.set(preloaded_song)
            self.load()

    def create_input_panel(self, master, row):
        file_pane = tk.LabelFrame(master, text="File")

        self.create_file_input(file_pane)
        self.create_part_list(file_pane)

        file_pane.columnconfigure(1, weight=1)
        file_pane.grid(row=row, columnspan=2, sticky="NEW")

    def create_file_input(self, master):
        self.input_filename = tk.StringVar(master)

        self.create_file_input_button(master, 0)

        tk.Entry(
            master,
            textvariable=self.input_filename
        ).grid(row=0, column=1, sticky="EW")

        ttk.Button(
            master,
            text="Load",
            command=self.load
        ).grid(row=0, column=2)

    def create_file_input_button(self, master, column):
        def select_file():
            self.input_filename.set(
                tkinter.filedialog.askopenfilename(
                    initialdir=sys.path[0],
                    defaultextension="json",
                    filetypes=[("JSON files", "json")]
                )
            )

        ttk.Button(
            master,
            text="Pick file",
            command=select_file
        ).grid(row=0, column=column)

    def create_part_list(self, master):
        canvas = tk.Canvas(
            master,
            height=0,
            bd=0,
            highlightthickness=0,
            relief="ridge"
        )
        scrollbar = ttk.Scrollbar(
            master,
            orient="horizontal",
            command=canvas.xview
        )
        canvas.configure(
            xscrollcommand=scrollbar.set,
            yscrollcommand=scrollbar.set
        )
        canvas.bind(
            "<Configure>",
            lambda _: canvas.configure(scrollregion=canvas.bbox('all'))
        )
        canvas.grid(row=1, columnspan=3, sticky="EW")
        scrollbar.grid(row=2, columnspan=3, sticky="EW")

        self.song_part_panel = tk.Frame(canvas)
        canvas.create_window((0, 0), window=self.song_part_panel, anchor='nw')

    def create_variant_layer_panel(self, master, row):
        self.variant_pane = self.create_track_panel(master, 'Variants', row, 0)
        self.layer_pane = self.create_track_panel(master, 'Layers', row, 1)

    def create_track_panel(self, master, label, row, column):
        frame = tk.LabelFrame(master, text=label)
        frame.grid(row=row, column=column, sticky="NESW")
        return frame

    def create_now_playing_panel(self, master, row):
        now_playing_frame = tk.LabelFrame(master, text="Now playing")

        self.create_now_playing_label(now_playing_frame)
        self.create_song_progress_bar(now_playing_frame)

        now_playing_frame.columnconfigure(0, weight=1)
        now_playing_frame.grid(row=row, columnspan=2, sticky="EW")

    def create_now_playing_label(self, master):
        self.now_playing = tk.StringVar(value="")
        tk.Label(
            master,
            textvariable=self.now_playing
        ).grid(row=0, sticky="EW")

    def create_song_progress_bar(self, master):
        self.progress_bar = ttk.Progressbar(
            master,
            mode="determinate"
        )
        self.progress_bar.grid(row=1, sticky="EW")

    def create_volume_panel(self, master, row):
        volume_panel = tk.Frame(master)

        self.create_pause_button(volume_panel)
        self.create_volume_bar(volume_panel)

        volume_panel.columnconfigure(2, weight=1)
        volume_panel.grid(row=row, columnspan=2, sticky='EW')

    def create_pause_button(self, master):
        self.pause_text = tk.StringVar(value='Pause')

        def toggle_pause():
            pause = not self.loaded_song.playback_state.paused
            self.loaded_song.playback_state.paused = pause
            self.pause_text.set(('Pause', 'Play')[pause])
        
        ttk.Button(
            master,
            textvariable=self.pause_text,
            command=toggle_pause
        ).grid(row=0, column=0)

    def set_volume(self, vol):
        vol = float(vol)
        try:
            self.loaded_song.playback_state.volume = vol
        except AttributeError:
            pass
        self.volume.set(f'Volume: {vol:3.0%}')

    def create_volume_bar(self, master):
        self.volume = tk.StringVar()
        self.set_volume(1.0)

        tk.Label(
            master,
            textvariable=self.volume
        ).grid(row=0, column=1, sticky='E')

        ttk.Scale(
            master,
            from_=0,
            to=1.0,
            value=1.0,
            orient='horizontal',
            command=self.set_volume
        ).grid(row=0, column=2, sticky='EW')

    def create_import_button(self, master, row):
        def open_importer():
            SCMImportGUI(create_window(master))
        ttk.Button(
            master,
            text="Import files from SmashCustomMusic archive...",
            command=open_importer
        ).grid(row=row, columnspan=2, sticky="SE")

    def load(self):
        input_file = self.input_filename.get()
        try:
            loaded_song = la.open_song(input_file)
            parts = loaded_song.parts
        except Exception as exc:
            dialog_and_print_error(exc, 'Could not load song')
            loaded_song = None
            parts = ()
        else:
            try:
                self.stop_playback()
            except AttributeError:
                pass
        finally:
            self.loaded_song = loaded_song

        self.populate_song_part_panel(parts)

    def populate_song_part_panel(self, partlist):
        self.clear_widget(self.song_part_panel)
        self.create_song_part_buttons(self.song_part_panel, partlist)
        self.create_stop_button(self.song_part_panel)

    def clear_widget(self, widget):
        for w in widget.winfo_children():
            w.destroy()

    def create_song_part_buttons(self, master, partlist):
        for num, part in enumerate(partlist):
            self.song_part_record(partlist, num, part)
        master.pack()

    def song_part_record(self, partlist, num: int, part: la.SongPart):
        button = ttk.Button(
            master=self.song_part_panel,
            text=part.name or ('Play' if len(partlist) == 1 else f'Part {num + 1}'),
            command=lambda: self.play_song_part(num)
        )
        button.pack(side=tk.LEFT)
        return {
            "name": part.name,
            "button": button
        }

    def create_stop_button(self, master):
        self.stop_button = ttk.Button(
            master,
            text="Stop",
            command=self.stop_playback
        )
        self.stop_button.state([tk.DISABLED])
        self.stop_button.pack(side=tk.LEFT)

    def stop_playback(self):
        self.pause_text.set('Pause')
        self.stop_button.state([tk.DISABLED])
        self.now_playing.set("")
        self.loaded_song.stop()
        self.loaded_song.playback_state.paused = False
        self.progress_bar["value"] = 0
        self.clear_widget(self.variant_pane)
        self.clear_widget(self.layer_pane)

    def play_song_part(self, partind):
        try:
            self.stop_playback()
        except AttributeError:
            pass
        finally:
            part = self.loaded_song.get_song(partind)
            self.set_active_song(partind, part)
        self.populate_variant_panel(part)
        self.populate_layer_panel(part)
        self.reset_song_variants_and_layers(part)
        self.update_now_playing(part)

    def set_active_song(self, part, loop):
        pb = SongProgressUpdater(loop, self.progress_bar)
        pb.start()
        self.loaded_song.play_async(part, callback=pb.update)
        self.stop_button.state([TTK_ENABLED])

    def populate_variant_panel(self, song):
        self.clear_widget(self.variant_pane)
        self.create_variant_radio_buttons(song)

    def create_variant_radio_buttons(self, song):
        selected_variant = tk.IntVar(master=self.variant_pane, value=0)
        variants = list(song.variants())

        def select_variant():
            song.set_variant(variants[selected_variant.get()])

        radiobuttons = [
            self.variant_radio_button(
                selected_variant,
                var,
                pos,
                select_variant
            )
            for pos, var in enumerate(variants)
        ]
        if radiobuttons:
            if radiobuttons[0]["text"] == "":
                radiobuttons[0]["text"] = "<default>"
            selected_variant.set(0)

    def variant_radio_button(self, variable, label, value, select_function):
        btn = ttk.Radiobutton(
            self.variant_pane,
            variable=variable,
            text=label,
            value=value,
            command=select_function
        )
        btn.pack(anchor=tk.W)
        return btn

    def populate_layer_panel(self, song):
        self.clear_widget(self.layer_pane)

        def layer_set_function(layer, variable):
            return lambda: song.set_layer_volume(layer, variable.get())

        self.activelayers = [self.layer_check_button(layer_set_function, lay)
            for lay in song.layers()]

    def layer_check_button(self, layer_set_function, lay):
        var = tk.IntVar()
        check = ttk.Checkbutton(
            self.layer_pane,
            variable=var,
            text=lay,
            command=layer_set_function(lay, var)
        )
        check.pack(anchor=tk.W)
        var.set(0)
        return var

    def reset_song_variants_and_layers(self, song):
        if song.variants():
            song.set_variant(next(iter(song.variants())))
            song.set_layers_from_bits(0)
        else:
            song.set_layers_from_bits(1)
            self.activelayers[0].set(1)
    
    def update_now_playing(self, song):
        self.now_playing.set('\n'.join(song.tags.to_str_list()))


def dialog_and_print_error(exception, message='An error occurred'):
    err = f'{message}:\n{exception}'
    traceback.print_exception(None, exception, exception.__traceback__)
    tkinter.messagebox.showerror(message=err)


class SCMImportGUI:

    def __init__(self, master: tk.Toplevel):
        master.title("SmashCustomMusic import")
        self.master = master
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
            default=tk.DISABLED,
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
            variable=self.use_json,
            command=self.update_json_use
        )
        json_btn.grid(row=0, column=0, sticky='W', padx=5)
        self.use_json.set(True)

    def create_file_selector(self, master):
        file_field = tk.Frame(master)
        self.file_name = tk.StringVar(file_field)
        tk.Label(file_field, text="File name").grid(row=0, column=0)
        tk.Entry(file_field, textvariable=self.file_name).grid(
            row=0, column=1, sticky="EW")
        ttk.Button(
            file_field,
            text="Select",
            command=lambda: self.file_name.set(
                tkinter.filedialog.asksaveasfilename(
                    initialdir=sys.path[0],
                    confirmoverwrite=True,
                    filetypes=[("JSON file", "json")]
                )
            )
        ).grid(row=0, column=2)
        file_field.columnconfigure(1, weight=1)
        file_field.grid(row=0, sticky="EW")

    def start_conversion(self):
        try:
            parts = [part.create_song_info() for part in self.parts]
            window, callback = self.create_conversion_progress_window(parts)
            if self.use_json.get():
                create_song(
                    self.file_name.get(),
                    parts,
                    callback=callback
                )
            else:
                create_song_audio_only(
                    self.file_name.get(),
                    parts[0],
                    callback=callback
                )
        except Exception as exc:
            dialog_and_print_error(exc, 'Could not create song files')
        else:
            tkinter.messagebox.showinfo(message="Loop created!")
        finally:
            window.destroy()

    def create_conversion_progress_window(self, parts: Sequence[SongPart]):
        window = tk.Toplevel(self.master)
        window.minsize(320, 1)
        window.columnconfigure(0, weight=1)
        window.resizable(False, True)
        
        labels = (
            tuple(4 + len(part.variants) + len(part.layers) for part in parts)
            + (1,)
        )

        songlabel = tk.StringVar(window)
        songprogress = tk.DoubleVar(window)
        tk.Label(
            window,
            textvariable=songlabel,
            wraplength=320
        ).grid(row=0, sticky="EW")
        ttk.Progressbar(
            window,
            maximum=len(labels) - 1,
            mode="determinate",
            variable=songprogress
        ).grid(row=1, sticky='EW')

        partlabel = tk.StringVar(window)
        partprogress = tk.IntVar(window)
        tk.Label(
            window,
            textvariable=partlabel,
            wraplength=320
        ).grid(row=2, sticky='EW')
        partbar = ttk.Progressbar(
            window,
            mode="determinate",
            variable=partprogress
        )
        partbar.grid(row=3, sticky="EW")

        bigpart = -1
        smallpart = 0
        nsmallparts = 1

        def callback(message):
            nonlocal partbar, bigpart, smallpart, nsmallparts

            if (len(message) == 2):
                big, small = message
            else:
                big, = message
                small = ""

            if big != songlabel.get():
                bigpart += 1
                smallpart = 0

                songlabel.set(big)

                nsmallparts = labels[bigpart]
                partbar["maximum"] = nsmallparts
            else:
                smallpart += 1
            
            partlabel.set(small)
            partprogress.set(smallpart)
            songprogress.set(bigpart + smallpart / nsmallparts)
            print(songprogress.get())
            
            print(message)
            partlabel.set(small)
            window.update()

        return window, callback

    def add_part(self):
        partui = SongPartUI(
            self.part_ui,
            row=0,
            nb=self.part_ui,
            index=len(self.parts),
            use_json=self.use_json
        )
        self.parts.append(partui)
        self.part_ui.add(partui.panel, text="<untitled>")
        disable_for_size(self.remove_part_button, self.parts, 1)

    def remove_part(self):
        partui = self.parts.pop()
        partui.panel.destroy()
        disable_for_size(self.remove_part_button, self.parts, 1)
    
    def update_json_use(self):
        enabled = tk.NORMAL if self.use_json.get() else tk.DISABLED
        allowed_part = self.parts[0]
        self.update_tab_usability(enabled)
        self.update_part_id_usability(enabled, allowed_part)
        self.update_track_name_usability(enabled, allowed_part)

    def update_tab_usability(self, active_state):
        for i in itertools.chain((0,), range(2, len(self.part_ui.tabs()))):
            self.part_ui.tab(i, state=active_state)
    
    def update_part_id_usability(self, active_state, part_ui: 'SongPartUI'):
        part_ui.filename_field.configure(state=active_state)
        part_ui.part_name_entry.configure(state=active_state)
    
    def update_track_name_usability(self, active_state, part_ui: 'SongPartUI'):
        self.enable_disable_tracks(active_state, part_ui.variants)
        self.enable_disable_tracks(active_state, part_ui.layers)
    
    def enable_disable_tracks(self, active_state, tracklist):
        for track in tracklist:
            track.name_entry.configure(state=active_state)

def disable_for_size(button: ttk.Button, collection: Sized, minsize: int):
    state = TTK_ENABLED if len(collection) > minsize else tk.DISABLED
    button.state([state])


class TkVarMetadata:
    def __init__(self, master):
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


def create_window(master, title=None):
    window = tk.Toplevel(master)
    if title is not None:
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
    EditableListEntry(master, sequence).frame.grid(row=row, column=1, sticky='NSEW')


class SongPartUI:

    def __init__(
        self,
        master,
        row,
        nb: ttk.Notebook,
        index: int,
        use_json: tk.BooleanVar
    ):
        self.panel = tk.Frame(master)
        self.use_json = use_json

        self.create_description_panel(nb, index)
        self.variant_panel, self.variants = self.create_track_panel(
            label='Variant',
            description='Different versions of the same song. Only one plays at at time.',
            row=3,
            minlength=1
        )
        self.layer_panel, self.layers = self.create_track_panel(
            label='Layer',
            description='Any combination of layers may play over the selected variant.',
            row=4,
            minlength=0
        )

        self.panel.rowconfigure(3, weight=1)
        self.panel.rowconfigure(4, weight=1)
        self.panel.columnconfigure(0, weight=1)
        self.panel.grid(row=row, sticky="NSEW")

    def create_description_panel(self, nb, index):
        name_panel = tk.LabelFrame(self.panel, text="Information")
        self.metadata = TkVarMetadata(name_panel)
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
        self.part_name_entry = create_field(
            master,
            'Part name:',
            self.part_name,
            1
        )
        self.part_name_entry.bind("<FocusOut>", set_widget_name)

    def create_filename_field(self, master):
        self.filename = tk.StringVar(self.panel)
        self.filename_field = create_field(master, 'Filename:', self.filename, 2)

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
    ) -> Tuple[tk.Widget, Sequence['SongPartUI.TrackFields']]:
        panel = tk.LabelFrame(self.panel, text=f'{label}s')
        tracks = []

        tk.Label(panel, text=description).grid(row=0, columnspan=2)
        self.create_table_header(label, panel)
        add_button, remove_button = self.create_track_buttons(
            minlength,
            panel,
            tracks
        )
        self.grid_buttons(add_button, remove_button, tracks, minlength)
        for _ in range(minlength):
            self.push_field(
                panel,
                tracks,
                add_button,
                remove_button,
                minlength
            )

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
                panel,
                tracks,
                add_button,
                remove_button,
                minlength
            ),
            text="+")
        remove_button = ttk.Button(
            panel,
            command=lambda: self.pop_field(
                tracks,
                add_button,
                remove_button,
                minlength
            ),
            text="-")

        return add_button, remove_button

    def grid_buttons(self, add, remove, collection, minsize):
        row = len(collection) + 2
        add.grid(row=row, column=0, sticky="EW")
        remove.grid(row=row, column=1, sticky="EW")
        disable_for_size(remove, collection, minsize)

    class TrackFields(NamedTuple):
        name: str
        url: str
        name_entry: tk.Entry
        url_entry: tk.Entry

    def push_field(
        self,
        panel: tk.PanedWindow,
        rowdata: Sequence['SongPartUI.TrackFields'],
        addbutton: ttk.Button,
        removebutton: ttk.Button,
        minsize: int
    ):
        name = tk.StringVar(panel)
        url = tk.StringVar(panel)
        row = len(rowdata) + 2
        nfield = self.create_track_entry(panel, name, row, 0)
        nfield.configure(
            state=tk.NORMAL if self.use_json.get() else tk.DISABLED
        )
        ufield = self.create_track_entry(panel, url, row, 1)
        rowdata.append(SongPartUI.TrackFields(name, url, nfield, ufield))

        self.grid_buttons(addbutton, removebutton, rowdata, minsize)

    def create_track_entry(self, master, variable, row, column):
        entry = tk.Entry(master, textvariable=variable)
        entry.grid(row=row, column=column, sticky="EW")
        return entry

    def pop_field(
        self,
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

    def create_song_info(self) -> SongPart:
        return SongPart(
            self.part_name.get(),
            self.filename.get(),
            self.metadata.to_get_brstm_meta(),
            [SongTrackURL(*var) for var in self.get_variants()],
            [SongTrackURL(*lay) for lay in self.get_layers()]
        )


def main(*args):
    window = tk.Tk()
    try:
        song = args[0]
    except IndexError:
        song = None
    LoopGUI(window, song)
    window.mainloop()


if __name__ == "__main__":
    import sys
    main(*sys.argv[1:])

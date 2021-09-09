import json
import queue as q
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePath
from threading import Event, Thread
from typing import Any, Callable, Mapping, MutableSequence, NamedTuple, Union

import mutagen
import numpy as np
import sounddevice as sd
import soundfile as sf


volume: float = 1.0
paused: bool = False


class LoopData(NamedTuple):
    start: int
    end: int


@dataclass(init=True, repr=True)
class TrackData:
    value: Any
    volume: float


def bitwise_iter(num: int, pad=False):
    """Return an iterator that yields bits from num in the order of least to
    most significant.
    
    If pad is false, this iterator will stop once num's bits are exhausted. If
    pad is true, then it will continue to yield zeros afterward."""
    while num > 0:
        yield num & 1
        num >>= 1
    while pad:
        yield 0


class SoundLoop:

    def __init__(
        self,
        audio_data: tuple,
        loopstart: int = 0,
        loopend: int = None
    ):
        self.loop = LoopData(loopstart, loopend)
        if None in self.loop:
            self.loop = None

        self.data = audio_data[0]
        self.sample_rate = audio_data[1]

    def create_playback(self):
        return SoundLoopPlayback(self)


class SoundLoopPlayback:

    def __init__(self, sound: SoundLoop):
        self.sound = sound
        self.current_frame = 0

    def stream_callback(self, outdata, frames, time, status):
        if status:
            print(status)
        chunksize = min(len(self.sound.data) - self.current_frame, frames)
        outdata[:chunksize] = self.sound.data[
            self.current_frame:self.current_frame + chunksize]
        if chunksize < frames:
            if self.sound.loop:
                self.current_frame = self.sound.loop.start + frames - chunksize
                outdata[chunksize:] = self.sound.data[
                    self.sound.loop.start:self.current_frame]
            else:
                outdata[chunksize:] = 0
                raise sd.CallbackStop()
        else:
            self.current_frame += chunksize


@dataclass(repr=True)
class SongTags:

    title: Any
    artist: Any
    album: Any
    number: Any
    year: Any
    game: Any

    def __init__(self, tags: Mapping = None, **kwargs):
        tags = {} if tags is None else tags
        def get_tag(tag: str):
            tag = tags.get(tag, kwargs.get(tag, None))
            if not tag:
                return None
            if len(tag) == 1:
                return next(iter(tag))
            return tag

        self.title = get_tag('title')
        self.artist = get_tag('artist')
        self.album = get_tag('album')
        self.number = None
        self.year = get_tag('date')
        self.game = get_tag('game')
    
    def __iter__(self):
        yield 'title', self.title
        yield 'artist', self.artist
        yield 'album', self.album
        yield 'game', self.game
        yield 'track number', self.number
        yield 'year', self.year

    def __bool__(self):
        return any(val for _, val in self)

    def to_str_list(self):
        def is_listable(obj):
            return isinstance(obj, Sequence) and not isinstance(obj, str)

        def list_form(item) -> tuple[bool, str]:
            if is_listable(item):
                return True, ', '.join(item)
            return False, str(item)

        data = []
        if self.title:
            data.append(str(self.title))
        if self.artist:
            _, artist = list_form(self.artist)
            data.append(artist)
        if self.album and self.game:
            data.append(f'Album: {self.album}')

            plural, game = list_form(self.game)
            data.append(f'{"Games" if plural else "Game"}: {game}')
        elif self.album:
            data.append(self.album)
        elif self.game:
            _, game = list_form(self.game)
            data.append(game)
        if self.number:
            data.append('#' + str(self.number))
        if self.year:
            data.append(str(self.year))
        return data

    def __str__(self):
        return '; '.join(self.to_str_list())


class SongLoop(ABC):

    loop: Union[LoopData, None]
    _tracks: MutableSequence[TrackData]

    def __init__(self,
                 tags: SongTags,
                 name: str,
                 variants: Union[Sequence, Mapping],
                 layers: Union[Sequence, Mapping, None] = None,
                 loopstart: int = 0,
                 loopend: int = None,
                 blocksize: int = 2048,
                 buffersize: int = 20
                ):
        self.tags, self.name, self.block_size, self.buffer_size = (
            tags, name, blocksize, buffersize)
        self.set_loop(loopstart, loopend)
        self._intialize_tracklist(variants, layers)

        self._dataqueue = q.Queue(maxsize=buffersize)
        self.stopped = False
        self._position = 0

    def set_loop(self, loopstart, loopend):
        self.loop = LoopData(loopstart, loopend)
        if None in self.loop:
            self.loop = None

    def _intialize_tracklist(self, variants, layers):
        self._tracks = []
        self._variants = self._register_trackset(variants)
        self._layers = self._register_trackset(layers)

        if variants:
            self.set_variant(next(iter(self.variants())))
        self._active_layers = set()

    def _register_trackset(self, tracklist):
        if tracklist is None:
            tracks = ()
        elif isinstance(tracklist, Sequence):
            tracks = self._register_track_seq(tracklist)
        else:
            tracks = self._register_track_map(tracklist)
        return tracks

    def _register_track_seq(self, tracklist):
        tracks = []
        for v in tracklist:
            index = len(self._tracks)
            tracks.append(index)
            self._tracks.append(TrackData(v, 0.0))
        return tracks

    def _register_track_map(self, tracklist):
        tracks = {}
        for n, v in tracklist.items():
            index = len(self._tracks)
            tracks[n] = index
            self._tracks.append(TrackData(v, 0.0))
        return tracks

    @abstractmethod
    def sample_rate(self) -> int:
        ...

    @property
    def position(self) -> int:
        return self._position

    @abstractmethod
    def seek(self, frames):
        ...

    @abstractmethod
    def _get_frames(self, frames: int):
        ...

    def read_data(self):
        self.read_data = self._read_looping_data if self.loop \
            else self._read_data
        return self.read_data()

    def _read_looping_data(self):
        remaining = self.loop.end - self._position
        if remaining < self.block_size:
            return self._read_end_of_loop(remaining)
        else:
            return self._get_frames(self.block_size)

    def _read_end_of_loop(self, remaining):
        alpha = self._get_frames(remaining)
        self.seek(self.loop.start)
        bravo = self._get_frames(self.block_size - len(alpha))
        concat = self._concatenate(alpha, bravo)
        return concat

    @abstractmethod
    def _concatenate(self, alpha, bravo):
        ...

    def _read_data(self):
        data = self._get_frames(self.block_size)
        return data
    
    def variants(self):
        if isinstance(self._variants, Sequence):
            return range(len(self._variants))
        return self._variants.keys()
    
    def layers(self):
        if isinstance(self._layers, Sequence):
            return range(len(self._layers))
        return self._layers.keys()
    
    def get_variant(self):
        return self._active_variant
    
    def _set_track_volume(self, track: int, volume: float):
        self._tracks[track].volume = volume

    def set_variant_volume(self, variant: Union[int, str], volume: float):
        self._set_track_volume(self._variants[variant], volume)
    
    def set_layer_volume(self, layer: Union[int, str], volume: float):
        self._set_track_volume(self._layers[layer], volume)

    def _set_variant(self, variant, volume):
        try:
            self.set_variant_volume(self._active_variant, 0.0)
        except AttributeError:
            pass
        self._active_variant = variant
        self.set_variant_volume(variant, volume)

    def set_variant(self, variant, *, volume: float = 1.0):
        if variant is None:
            self._active_variant = None
            return
        try:
            self._variants[variant]
        except (IndexError, KeyError) as e:
            raise ValueError(str(variant) + " does not exist") from e
        else:
            self._set_variant(variant, volume)

    def get_active_layers(self):
        return tuple(self._active_layers)

    def _set_layer(self, layer, operation):
        try:
            self._layers[layer]
        except (IndexError, KeyError) as e:
            raise ValueError(str(layer) + " does not exist") from e
        else:
            operation(layer)

    def add_layer(self, layer):
        self.set_layer_volume(layer, 1.0)
        self._set_layer(self, layer, self._active_layers.add)

    def set_layer(self, layer, value):
        self.set_layer_volume(layer, float(value))
        self._set_layer(
            layer,
            self._active_layers.add if value else self._active_layers.discard
        )

    def remove_layer(self, layer):
        self.set_layer_volume(layer, 0.0)
        self._set_layer(self, layer, self._active_layers.discard)

    def add_layers(self, layers: Iterable):
        for layer in layers:
            try:
                self.add_layer(layer)
            except ValueError:
                pass

    def remove_layers(self, layers: Iterable):
        for layer in layers:
            try:
                self.remove_layer(layer)
            except ValueError:
                pass
    
    def set_layers(self, layers: Union[Iterable, int]):
        if isinstance(layers, Iterable):
            self.set_layers_from_names(layers)
        else:
            self.set_layers_from_bits(layers)

    def set_layers_from_names(self, layers: Iterable):
        self.remove_layers(self.layers())
        self.add_layers(layers)

    def set_layers_from_bits(self, layers: int):
        for layer, bit in zip(self._layers, bitwise_iter(layers, pad=True)):
            self.set_layer(layer, bit)

    def play(self,
             start=0,
             stream: sd.OutputStream = None,
             callback: Callable = None,
             finish_event: Event = None
            ):
        if callback is None:
            def callback():
                pass

        self._restart_from(start)

        finish_event = finish_event or Event()
        if stream is None:
            stream = sd.OutputStream(
                samplerate=self.sample_rate(),
                blocksize=self.block_size,
                channels=self.channels(),
                callback=self.stream_callback,
                finished_callback=finish_event.set
            )
        with stream:
            self._enqueue_data_until_stopped(callback)
            finish_event.wait()

    def _restart_from(self, start):
        self.seek(start)
        self.stopped = False
        self.prefill_queue()

    def prefill_queue(self):
        for _ in range(self.buffer_size):
            data = self.read_data()
            if not len(data):
                break
            self._dataqueue.put_nowait(data)
    
    def _enqueue_data_until_stopped(self, callback):
        data = [0]
        while len(data) and not self.stopped:
            callback()
            data = self.read_data()
            self._dataqueue.put(data)
        if self.stopped:
            with self._dataqueue.mutex:
                self._dataqueue.queue.clear()
        self._dataqueue.put(self._get_frames(0))

    def play_async(self, start=0, callback = None) -> Event:
        finish = Event()
        Thread(
            daemon=True,
            target=lambda: self.play(
                start=start,
                callback=callback,
                finish_event=finish
            )
        ).start()
        return finish

    def stop(self):
        self.stopped = True

    def stream_callback(self, outdata, frames, time, status):
        self._raise_for_stream_status(frames, status)
        data = self._get_stream_data()
        self._copy_data_into_stream(outdata, data)

    def _raise_for_stream_status(self, frames, status):
        assert frames == self.block_size
        if status.output_underflow:
            raise sd.CallbackAbort('Output underflow: increase blocksize?')
        assert not status

    def _get_stream_data(self):
        try:
            if paused:
                data = np.zeros((self.block_size, 2))
            else:
                data = self._dataqueue.get_nowait()
                data = self._mix_data(data) * volume
        except q.Empty as e:
            raise sd.CallbackAbort(
                'Buffer is empty: increase buffersize?') from e
        return data
    
    def _copy_data_into_stream(self, outdata, indata):
        if len(indata) < len(outdata):
            outdata[:len(indata)] = indata
            outdata[len(indata):].fill(0)
            raise sd.CallbackStop
        else:
            outdata[:] = indata
    
    def __len__(self):
        if self.loop:
            return self.loop.end
        else:
            return self.file_length()
    
    @abstractmethod
    def file_length(self):
        ...
    
    @abstractmethod
    def _mix_data(self, data) -> np.ndarray:
        ...
    
    @abstractmethod
    def channels(self):
        ...


class MultiTrackLoop(SongLoop):

    def __init__(self,
                 tags: SongTags,
                 name: str,
                 soundfile: sf.SoundFile,
                 variants: Union[Sequence, Mapping],
                 layers: Union[Sequence, Mapping] = None,
                 loopstart: int = 0,
                 loopend: int = None,
                 channels: int = 2,
                 blocksize: int = 2048,
                 buffersize: int = 20
                ):
        super().__init__(
            tags,
            name,
            variants,
            layers,
            loopstart,
            loopend,
            blocksize,
            buffersize
        )
        
        if not soundfile.seekable():
            self.loop = None
        
        self.sound_file = soundfile
        channels = channels or soundfile.channels
        self.channels = lambda: channels
    
    def channels(self):
        ...

    def sample_rate(self) -> int:
        return self.sound_file.samplerate

    def _get_frames(self, block_size):
        data = self.sound_file.read(block_size)
        self._position += len(data)
        return data

    def seek(self, frames: int):
        if frames < 0:
            self._position = self.sound_file.seek(frames, whence=sf.SEEK_END)
        else:
            self._position = self.sound_file.seek(frames)
    
    def file_length(self):
        return self.sound_file.frames

    def _mix_data(self, data):
        def get_range(trackno):
            return trackno * self.channels(), (trackno + 1) * self.channels()

        parts = []
        for track in self._tracks:
            trange = get_range(track.value)
            parts.append(data[:, trange[0]:trange[1]] * track.volume)
        return np.clip(sum(parts), -1.0, 1.0)
    
    def _concatenate(self, alpha, bravo):
        return np.concatenate((alpha, bravo))


class MultiFileLoop(SongLoop):

    def __init__(self,
                 tags: SongTags,
                 name: str,
                 variants: (
                    Union[Sequence[sf.SoundFile],
                    Mapping[Any, sf.SoundFile]]
                 ),
                 layers: (
                    Union[Sequence[sf.SoundFile],
                    Mapping[Any, sf.SoundFile], None]
                 ) = None,
                 loopstart: int = 0,
                 loopend: int = 0,
                 blocksize: int = 2048,
                 buffersize: int = 20
                ):
        super().__init__(
            tags,
            name,
            variants,
            layers,
            loopstart,
            loopend,
            blocksize,
            buffersize
        )

        # TODO maybe ensure the tracks are compatible

        first = next(iter(self._tracks)).value
        self.sample_rate = lambda: first.samplerate
        self.file_length = lambda: first.frames
        self.channels = lambda: first.channels
    
    def sample_rate(self):
        ...
    
    def file_length(self):
        ...
    
    def channels(self):
        ...

    def _get_frames(self, block_size):
        return [t.value.read(block_size) for t in self._tracks]

    def seek(self, frames: int):
        for file in self._tracks:
            self._position = file.value.seek(frames)
    
    def _mix_data(self, data):
        return np.clip(
            sum(d * t.volume for d, t in zip(data, self._tracks)), -1.0, 1.0)
    
    def _concatenate(self, alpha, bravo):
        return [np.concatenate((a, b)) for a, b in zip(alpha, bravo)]


def open_loop(
    filename: str,
    buffersize: int = 20,
    blocksize: int = 2048
) -> Union[None, SongLoop, Sequence[SongLoop]]:
    loops = open_loops(filename, buffersize, blocksize)
    if len(loops) == 0:
        return None
    if len(loops) == 1:
        return loops[0]
    return loops


def open_loops(
    filename: str,
    buffersize: int = 20,
    blocksize: int = 2048
) -> Sequence[SongLoop]:
    path = PurePath(filename)
    part_list = create_part_list(path)


    return [get_song_part(buffersize, blocksize, path, partinfo)
        for partinfo in part_list]


def create_part_list(path: PurePath):
    if path.suffix == '.json':
        file_list = json.load(open(path, 'r'))
        if not isinstance(file_list, Sequence):
            file_list = [file_list]
    else:
        file_list = [
            {
                'filename': path.name,
                'version': 2,
                'layers': ...}
        ]

    return file_list


def get_song_part(buffersize, blocksize, path: PurePath, partjson: Mapping):
    file = get_main_filename(path, partjson)
    tags = mutagen.File(file)
    song_tags = SongTags(tags)

    loopstart, loopend = get_loop_data(partjson, tags)
    part_name = partjson.get('name', 'Play')

    return [
        lambda: get_classic_loop(
            buffersize,
            blocksize,
            path,
            partjson,
            song_tags,
            loopstart,
            loopend,
            part_name
        ),
        lambda: get_multitrack_loop(
            buffersize,
            blocksize,
            partjson,
            file,
            song_tags,
            loopstart,
            loopend,
            part_name
        )
    ][partjson.get('version', 1) - 1]()


def get_main_filename(path: PurePath, partjson: Mapping):
    try:
        file = str(path.parent / partjson['filename'])
    except KeyError:
        varname = partjson['variants'][0]
        if varname:
            varname = f'-{varname}'
        file = (f'{path.parent / path.stem}{varname}.'
            + partjson.get("filetype", "wav"))
    return file


def get_loop_data(partjson, tags):
    try:
        loopstart = int(tags['loopstart'][0])
        loopend = loopstart + int(tags['looplength'][0])
    except KeyError:
        loopstart = None
        loopend = None

    try:
        loopstart = partjson['loopstart']
        loopend = partjson['loopend']
    except KeyError:
        pass
    return loopstart, loopend


def get_classic_loop(
    buffersize,
    blocksize,
    path: PurePath,
    partjson: Mapping,
    song_tags,
    loopstart,
    loopend,
    part_name
):
    return MultiFileLoop(
        song_tags,
        part_name,
        get_classic_tracks(path, partjson, 'variants'),
        get_classic_tracks(path, partjson, 'layers'),
        loopstart,
        loopend,
        blocksize,
        buffersize
    )

def get_classic_tracks(path: PurePath, partjson: Mapping, key):
    tracks = {}
    for variant in partjson.get(key, ()):
        var_name = '-' + variant if variant else ''
        tracks[variant] = sf.SoundFile(
            f'{path.parent / path.stem}{var_name}.'
                + partjson.get("filetype", "wav")
        )
    return tracks


def get_multitrack_loop(
    buffersize,
    blocksize,
    partjson: Mapping,
    path: PurePath,
    song_tags,
    loopstart,
    loopend,
    part_name
):
    file = sf.SoundFile(str(path))
    variants = partjson.get('variants', [])
    layers = partjson.get('layers', None)
    if layers is None:
        layers = []
    if layers is ...:
        layers = range(0, file.channels // 2)
    return MultiTrackLoop(
        song_tags,
        part_name,
        file,
        variants,
        layers,
        loopstart,
        loopend,
        2,
        blocksize,
        buffersize
    )

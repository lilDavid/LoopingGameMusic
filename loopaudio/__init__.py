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


class LoopPoints(NamedTuple):
    """A song part's loop points. The song will play to *start* samples, then
    play the section from *start* to *end* samples indefinitely."""

    start: int
    end: int


@dataclass(init=True, repr=True)
class TrackState:
    """The enabled/disabled state of a track.

    The player in the GUI module only uses 0.0 and 1.0 for the volume, however
    using any other numeric value is possible and will work."""

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
    """A reusable sound loaded into memory all at once."""

    def __init__(
        self,
        audio_data,
        sample_rate: int,
        loopstart: int = 0,
        loopend: int = None
    ):
        self.loop = LoopPoints(loopstart, loopend)
        if None in self.loop:
            self.loop = None

        self.data, self.sample_rate = audio_data, sample_rate

    def create_playback(self):
        """Create a playback object for this sound."""

        return SoundLoopPlayback(self)


class SoundLoopPlayback:
    """An object used to play a SoundLoop."""

    def __init__(self, sound: SoundLoop):
        self.sound = sound
        self.current_frame = 0

    def stream_callback(self, outdata, frames, time, status):
        """Write the data from the original sound into a stream."""

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
    """Tag data for a song, consisting of info used to identify the song and its
    source, but not necessary for playback.

    Of these, the title field is the most likely to be filled, but even that
    isn't strictly necessary."""

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
        yield self.title
        yield self.artist
        yield self.album
        yield self.game
        yield self.number
        yield self.year

    def __bool__(self):
        return any(self)

    def to_str_list(self):
        """Construct a string list describing all tags that are set in this object."""

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


class SongPart(ABC):
    """A streamed loop for music files that supports variable mixing."""

    loop: Union[LoopPoints, None]
    _tracks: MutableSequence[TrackState]

    def __init__(self,
                 tags: SongTags,
                 name: str,
                 variants: Union[Sequence, Mapping],
                 layers: Union[Sequence, Mapping, None] = None,
                 loopstart: int = 0,
                 loopend: int = None
                 ):
        self.tags, self.name = tags, name
        self.set_loop(loopstart, loopend)
        self._intialize_tracklist(variants, layers)

        self._position = 0

    def set_loop(self, start, end):
        """Set the song's loop points. If either point is None, then the song
        will only play once and not loop."""

        self.loop = LoopPoints(start, end)
        if None in self.loop:
            self.loop = None
            self.read_data = self._get_frames
        else:
            self.read_data = self._read_looping_data

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
            self._tracks.append(TrackState(v, 0.0))
        return tracks

    def _register_track_map(self, tracklist):
        tracks = {}
        for n, v in tracklist.items():
            index = len(self._tracks)
            tracks[n] = index
            self._tracks.append(TrackState(v, 0.0))
        return tracks

    @abstractmethod
    def sample_rate(self) -> int:
        """Get and return the song's sample rate in hertz."""

        ...

    @property
    def position(self) -> int:
        """The playhead position in samples."""

        return self._position

    @abstractmethod
    def seek(self, frames: int):
        """Set the position of the playhead."""

        ...

    @abstractmethod
    def _get_frames(self, frames: int):
        ...

    def read_data(self, amount: int):
        """Read the next data chunk and advance the playhead accordingly."""

        self.read_data = self._read_looping_data if self.loop \
            else self._get_frames
        return self.read_data(amount)

    def _read_looping_data(self, amount):
        remaining = self.loop.end - self._position
        if remaining < amount:
            return self._read_end_of_loop(remaining, amount)
        else:
            return self._get_frames(amount)

    def _read_end_of_loop(self, remaining, total):
        alpha = self._get_frames(remaining)
        self.seek(self.loop.start)
        bravo = self._get_frames(total - len(alpha))
        concat = self._concatenate(alpha, bravo)
        return concat

    @abstractmethod
    def _concatenate(self, alpha, bravo):
        ...

    def variants(self):
        """Get and return the song's set of variant names or numbers."""

        if isinstance(self._variants, Sequence):
            return range(len(self._variants))
        return self._variants.keys()

    def layers(self):
        """Get and return the song's set of layer names or numbers."""

        if isinstance(self._layers, Sequence):
            return range(len(self._layers))
        return self._layers.keys()

    def get_variant(self):
        """Get and return the name or number of the currently playing variant."""

        return self._active_variant

    def _set_track_volume(self, track: int, volume: float):
        self._tracks[track].volume = volume

    def _set_variant_volume(self, variant: Union[int, str], volume: float):
        self._set_track_volume(self._variants[variant], volume)

    def _set_layer_volume(self, layer: Union[int, str], volume: float):
        self._set_track_volume(self._layers[layer], volume)

    def _set_variant(self, variant, volume):
        try:
            self._set_variant_volume(self._active_variant, 0.0)
        except AttributeError:
            pass
        self._active_variant = variant
        self._set_variant_volume(variant, volume)

    def set_variant(self, variant, *, volume: float = 1.0):
        """Set the currently playing variant."""

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
        """Get the names of the layers that are currently playing."""

        return tuple(self._active_layers)

    def _set_layer(self, layer, operation):
        try:
            self._layers[layer]
        except (IndexError, KeyError) as e:
            raise ValueError(str(layer) + " does not exist") from e
        else:
            operation(layer)

    def add_layer(self, layer, volume=1.0):
        """Enable a layer."""

        self._set_layer_volume(layer, volume)
        self._set_layer(layer, self._active_layers.add)

    def set_layer_volume(self, layer, volume):
        """Set the volume for a layer."""

        self._set_layer_volume(layer, float(volume))
        self._set_layer(
            layer,
            self._active_layers.add if volume else self._active_layers.discard
        )

    def remove_layer(self, layer):
        """Disable a layer."""

        self._set_layer_volume(layer, 0.0)
        self._set_layer(layer, self._active_layers.discard)

    def add_layers(self, layers: Iterable):
        """Enable layers from the iterable."""

        for layer in layers:
            try:
                self.add_layer(layer)
            except ValueError:
                pass

    def remove_layers(self, layers: Iterable):
        """Disable layers from the iterable."""

        for layer in layers:
            try:
                self.remove_layer(layer)
            except ValueError:
                pass

    def set_layers(self, layers: Union[Iterable, int]):
        """Set the song's layers based on the provided object, either based on
        the names, or the set bits if it's an integer."""

        if isinstance(layers, Iterable):
            self.set_layers_from_names(layers)
        else:
            self.set_layers_from_bits(layers)

    def set_layers_from_names(self, layers: Iterable):
        """Enable and disable the song's layers based on the names or numbers 
        present in the iterable."""

        self.remove_layers(self.layers())
        self.add_layers(layers)

    def set_layers_from_bits(self, layers: int):
        """Enable and disable the song's layers based on the set bits in the
        integer.

        The integer is read from least to most significant bit, so the first
        variant will be set based on the last bit, and so on."""

        for layer, bit in zip(self._layers, bitwise_iter(layers, pad=True)):
            self.set_layer_volume(layer, bit)

    def prefill(self, queue: q.Queue, blocksize):
        """Preload the song's data into the given queue."""

        for _ in range(queue.maxsize):
            data = self.read_data(blocksize)
            if not len(data):
                break
            queue.put_nowait(data)

    def enqueue_data_until_stopped(self, queue: q.Queue, blocksize, stop_state, callback=None):
        """Continuously load song data until the song is stopped.

        This will block until then."""

        if callback is None:
            def callback():
                pass

        data = [0]
        while len(data) and not stop_state.stopped:
            callback()
            data = self.read_data(blocksize)
            queue.put(data)
        if stop_state.stopped:
            with queue.mutex:
                queue.queue.clear()
        queue.put(self._get_frames(0))

    def __len__(self):
        if self.loop:
            return self.loop.end
        else:
            return self.file_length()

    @abstractmethod
    def file_length(self):
        """Get and return the length of the file in samples."""

        ...

    @abstractmethod
    def _mix_data(self, data) -> np.ndarray:
        ...

    @abstractmethod
    def channels(self):
        """Get and return the number of channels per track."""

        ...


class MultiTrackLoop(SongPart):

    def __init__(self,
                 tags: SongTags,
                 name: str,
                 soundfile: sf.SoundFile,
                 variants: Union[Sequence, Mapping],
                 layers: Union[Sequence, Mapping] = None,
                 loopstart: int = 0,
                 loopend: int = None,
                 channels: int = 2
                 ):
        super().__init__(
            tags,
            name,
            variants,
            layers,
            loopstart,
            loopend
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


class MultiFileLoop(SongPart):

    def __init__(
        self,
        tags: SongTags,
        name: str,
        variants: (Union[Sequence[sf.SoundFile], Mapping[Any, sf.SoundFile]]),
        layers: (Union[Sequence[sf.SoundFile], Mapping[Any, sf.SoundFile], None]) = None,
        loopstart: int = 0,
        loopend: int = 0
    ):
        super().__init__(
            tags,
            name,
            variants,
            layers,
            loopstart,
            loopend
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


class StreamPlayback:

    def __init__(
        self,
        owner: 'GameMusic',
        blocksize: int,
        song: SongPart,
        finish_event: Event = None
    ):
        self._finish_event = finish_event or Event()
        self.owner = owner
        self.song = song
        self.stopped = False

        def stream_callback(outdata, frames, time, status):
            if self.stopped:
                raise sd.CallbackStop
            self._raise_for_stream_status(status)
            if owner.playback_state.paused:
                data = np.zeros((frames, 2))
            else:
                data = owner._get_stream_data()
            self._copy_data_into_stream(outdata, data)

        self.stream = sd.OutputStream(
            samplerate=song.sample_rate(),
            blocksize=blocksize,
            channels=song.channels(),
            callback=stream_callback,
            finished_callback=self._finish_event.set
        )
    
    def is_finished(self):
        return self._finish_event.is_set()
    
    def await_finish(self):
        self._finish_event.wait()
    
    def stop(self):
        self.stopped = True
    
    def _raise_for_stream_status(self, status):
        if status.output_underflow:
            raise sd.CallbackAbort('Output underflow: increase blocksize?')
        assert not status

    def _copy_data_into_stream(self, outdata, indata):
        if len(indata) < len(outdata):
            outdata[:len(indata)] = indata
            outdata[len(indata):].fill(0)
            raise sd.CallbackStop
        else:
            outdata[:] = indata


class GameMusic:

    @dataclass
    class PlaybackState:
        paused: bool = False
        volume: float = 1.0

    def __init__(self, parts: Iterable[SongPart], buffersize = 20):
        self.parts = tuple(parts)
        self.parts_by_name = {part.name: part for part in parts}

        self.now_playing = None
        self._dataqueue = q.Queue(maxsize=buffersize)
        self.playback_state = GameMusic.PlaybackState()

    def get_song(self, song) -> SongPart:
        try:
            return self.parts[song]
        except IndexError:
            pass
        return self.parts_by_name[song]
    
    def __len__(self):
        return len(self.parts)

    def __contains__(self, song):
        return song in self.parts_by_name or song in range(len(self.parts))
    
    def part_names(self):
        return self.parts_by_name.keys()

    def play(
        self,
        song_index=0,
        start=0,
        callback: Callable = None,
        finish_event: Event = None
    ):
        """Play the song to a new stream."""

        song = self.get_song(song_index)
        song.seek(start)
        self._dataqueue = q.Queue(self._dataqueue.maxsize)
        song.prefill(self._dataqueue, blocksize=2048)

        self.stop()
        self.now_playing = StreamPlayback(self, 2048, song, finish_event)
        
        with self.now_playing.stream:
            play = self.now_playing
            song.enqueue_data_until_stopped(self._dataqueue, 2048, self.now_playing, callback)
            play.await_finish()

    def play_async(self, song_index=0, start=0, callback=None) -> Event:
        """Play the song in a new thread and return the event that will be set
        if and when it finishes."""

        finish = Event()
        Thread(
            daemon=True,
            target=lambda: self.play(song_index, start, callback, finish_event=finish)
        ).start()
        return finish

    def stop(self):
        """Stop the song's playback."""

        if self.now_playing is not None:
            self.now_playing.stop()
            self.now_playing = None
    
    def _get_stream_data(self):
        try:
            data = self._dataqueue.get_nowait()
            data = self.now_playing.song._mix_data(data) * self.playback_state.volume
        except q.Empty as e:
            raise sd.CallbackAbort('Buffer is empty: increase buffersize?') from e
        return data


def open_song(
    filename: str,
    buffersize: int = 20
) -> GameMusic:
    """Open a song and return it as a sequence of SongLoop objects."""

    path = PurePath(filename)
    part_list = _create_part_list(path)
    part_list = [_get_song_part(path, partinfo) for partinfo in part_list]
    return GameMusic(part_list, buffersize)


def _create_part_list(path: PurePath):
    if path.suffix == '.json':
        file_list = json.load(open(path, 'r'))
        if not isinstance(file_list, Sequence):
            file_list = [file_list]
    else:
        file_list = [{'filename': path.name, 'version': 2, 'layers': ...}]

    return file_list


def _get_song_part(path: PurePath, partjson: Mapping):
    file = _get_main_filename(path, partjson)
    tags = mutagen.File(file)
    song_tags = SongTags(tags)

    loopstart, loopend = _get_loop_data(partjson, tags)
    part_name = partjson.get('name', 'Play')

    return [
        lambda: _get_classic_loop(
            path,
            partjson,
            song_tags,
            loopstart,
            loopend,
            part_name
        ),
        lambda: _get_multitrack_loop(
            partjson,
            file,
            song_tags,
            loopstart,
            loopend,
            part_name
        )
    ][partjson.get('version', 1) - 1]()


def _get_main_filename(path: PurePath, partjson: Mapping):
    try:
        file = str(path.parent / partjson['filename'])
    except KeyError:
        varname = partjson['variants'][0]
        if varname:
            varname = f'-{varname}'
        file = (f'{path.parent / path.stem}{varname}.'
                + partjson.get("filetype", "wav"))
    return file


def _get_loop_data(partjson, tags):
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


def _get_classic_loop(
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
        _get_classic_tracks(path, partjson, 'variants'),
        _get_classic_tracks(path, partjson, 'layers'),
        loopstart,
        loopend
    )


def _get_classic_tracks(path: PurePath, partjson: Mapping, key):
    tracks = {}
    for variant in partjson.get(key, ()):
        var_name = '-' + variant if variant else ''
        tracks[variant] = sf.SoundFile(
            f'{path.parent / path.stem}{var_name}.'
            + partjson.get("filetype", "wav")
        )
    return tracks


def _get_multitrack_loop(
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
        2
    )

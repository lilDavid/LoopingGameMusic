import itertools
import json
import queue as q
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from os.path import basename, dirname, splitext
from threading import Event, Thread
from typing import Any, Callable, Mapping, NamedTuple, Union

import audio_metadata as am
import numpy as np
import sounddevice as sd
import soundfile as sf
from audio_metadata.exceptions import UnsupportedFormat


class LoopData(NamedTuple):
    start: int
    end: int


@dataclass(init=True, repr=True)
class TrackData:
    value: Any
    volume: float


# loaded into memory all at once, and reusable as a result
class SoundLoop:

    def __init__(self, audio_data: tuple, loopstart: int = 0, loopend: int = None):
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
        outdata[:chunksize] = self.sound.data[self.current_frame:self.current_frame + chunksize]
        if chunksize < frames:
            if self.sound.loop:
                self.current_frame = self.sound.loop.start + frames - chunksize
                outdata[chunksize:] = self.sound.data[self.sound.loop.start:self.current_frame]
            else:
                outdata[chunksize:] = 0
                raise sd.CallbackStop()
        else:
            self.current_frame += chunksize


# streamed into memory - probably has to be unique
class SongLoop(ABC):

    loop: Union[LoopData, None]
    _tracks: Sequence[TrackData]

    def __init__(self,
                 title: str,
                 name: str,
                 variants: Union[Sequence, Mapping],
                 layers: Union[Sequence, Mapping, None] = None,
                 loopstart: int = 0,
                 loopend: int = None,
                 blocksize: int = 2048,
                 buffersize: int = 20
                ):
        self.title = title
        self.name = name

        self.loop = LoopData(loopstart, loopend)
        if None in self.loop:
            self.loop = None
        
        self._tracks = []

        if isinstance(variants, Sequence):
            self._variants = []
            for v in variants:
                index = len(self._tracks)
                self._variants.append(index)
                self._tracks.append(TrackData(v, 0.0))
        else:
            self._variants = {}
            for n, v in variants.items():
                index = len(self._tracks)
                self._variants[n] = index
                self._tracks.append(TrackData(v, 0.0))
        
        if layers is None:
            self._layers = []
        elif isinstance(layers, Sequence):
            self._layers = []
            for l in layers:
                index = len(self._tracks)
                self._layers.append(index)
                self._tracks.append(TrackData(l, 0.0))
        else:
            self._layers = {}
            for n, l in layers.items():
                index = len(self._tracks)
                self._layers[n] = index
                self._tracks.append(TrackData(l, 0.0))

        if variants:
            self.set_variant(next(iter(self.variants())))
        self._active_layers = set()

        self.block_size = blocksize
        self.buffer_size = buffersize

        self._dataqueue = q.Queue(maxsize=buffersize)
        self.stopped = False
        self._position = 0

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
            alpha = self._get_frames(remaining)
            self.seek(self.loop.start)
            bravo = self._get_frames(self.block_size - len(alpha))
            concat = self._concatenate(alpha, bravo)
            return concat
        else:
            data = self._get_frames(self.block_size)
            return data

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
    
    def set_track_volume(self, track: int, volume: float):
        assert isinstance(self._tracks[track], TrackData)
        self._tracks[track].volume = volume

    def set_variant_volume(self, variant: Union[int, str], volume: float):
        self.set_track_volume(self._variants[variant], volume)
    
    def set_layer_volume(self, layer: Union[int, str], volume: float):
        self.set_track_volume(self._layers[layer], volume)

    def set_variant(self, variant, fade: float = 0.0):
        if variant is None:
            self._active_variant = None
            return
        try:
            self._variants[variant]
        except (IndexError, KeyError) as e:
            raise ValueError(str(variant) + " does not exist") from e
        else:
            try:
                self.set_variant_volume(self._active_variant, 0.0)
            except AttributeError:
                pass
            self._active_variant = variant
            self.set_variant_volume(variant, 1.0)

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
            self.remove_layers(self.layers())
            self.add_layers(layers)
        else:
            it = iter(self._layers)
            try:
                while layers > 0:
                    layer = next(it)
                    if layers & 1:
                        self._active_layers.add(layer)
                    else:
                        self._active_layers.discard(layer)
                    layers >>= 1
            except StopIteration:
                pass

    def play(self,
             start=0,
             stream: sd.OutputStream = None,
             callback: Callable = None,
             finish_event: Event = None
            ):
        if callback is None:
            def callback():
                pass

        self.seek(start)
        self.stopped = False

        for _ in range(self.buffer_size):
            data = self.read_data()
            if not len(data):
                break
            self._dataqueue.put_nowait(data)  # Pre-fill queue

        finish_event = finish_event or Event()

        if stream is None:
            stream = sd.OutputStream(
                samplerate=self.sample_rate(),
                blocksize=self.block_size,
                channels=self.channels,
                callback=self.stream_callback,
                finished_callback=finish_event.set
            )

        with stream:
            timeout = self.block_size * self.buffer_size / self.sample_rate()
            data = [0]
            while len(data) and not self.stopped:
                callback()
                data = self.read_data()
                self._dataqueue.put(data, timeout=timeout)
            if self.stopped:
                with self._dataqueue.mutex:
                    self._dataqueue.queue.clear()
            self._dataqueue.put(self._get_frames(0))
            finish_event.wait()

    def play_async(self, start=0, callback = None) -> Event:
        finish = Event()
        Thread(
            daemon=True,
            target=lambda: self.play(start=start, callback=callback, finish_event=finish)
        ).start()
        return finish

    def stop(self):
        self.stopped = True

    def stream_callback(self, outdata, frames, time, status):
        assert frames == self.block_size
        if status.output_underflow:
            print('Output underflow: increase blocksize?', file=sys.stderr)
            raise sd.CallbackAbort
        assert not status
        try:
            data = self._mix_data(self._dataqueue.get_nowait())
        except q.Empty as e:
            print('Buffer is empty: increase buffersize?', file=sys.stderr)
            raise sd.CallbackAbort from e
        if len(data) < len(outdata):
            outdata[:len(data)] = data
            outdata[len(data):].fill(0)
            raise sd.CallbackStop
        else:
            outdata[:] = data
    
    def __len__(self):
        if self.loop:
            return self.loop.end
        else:
            return self.file_length()
    
    @abstractmethod
    def file_length(self):
        ...
    
    @abstractmethod
    def _mix_data(self, data):
        ...


class MultiTrackLoop(SongLoop):

    def __init__(self,
                 title: str,
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
        super().__init__(title, name, variants, layers, loopstart, loopend, blocksize, buffersize)
        
        if not soundfile.seekable():
            self.loop = None
        
        # print(
        #     f'loop length: {loopend - loopstart}, mod blocksize: {(loopend - loopstart) % blocksize}')
        
        self.sound_file = soundfile
        self.channels = channels or soundfile.channels
    
    def sample_rate(self) -> int:
        return self.sound_file.samplerate

    def _get_frames(self, block_size):
        data = self.sound_file.read(block_size)
        
        self._position += len(data)
        # if len(data) != block_size:
        #     print(f'Warning: Wrong block size. Expected {block_size}, got {len(data)}')
        return data

    def seek(self, frames: int):
        if frames < 0:
            self._position = self.sound_file.seek(frames, whence=sf.SEEK_END)
        else:
            self._position = self.sound_file.seek(frames)
    
    def file_length(self):
        return self.sound_file.frames

    def _mix_data(self, data):
        def get_range(variant):
            return variant * self.channels, (variant + 1) * self.channels

        parts = []
        for track in self._tracks:
            trange = get_range(track.value)
            parts.append(data[:, trange[0]:trange[1]] * track.volume)
        return np.clip(sum(parts), -1.0, 1.0)
    
    def _concatenate(self, alpha, bravo):
        return np.concatenate((alpha, bravo))


class MultiFileLoop(SongLoop):

    def __init__(self,
                 title: str,
                 name: str,
                 variants: Union[Sequence[sf.SoundFile], Mapping[Any, sf.SoundFile]],
                 layers: Union[Sequence[sf.SoundFile], Mapping[Any, sf.SoundFile], None] = None,
                 loopstart: int = 0,
                 loopend: int = 0,
                 blocksize: int = 2048,
                 buffersize: int = 20
                ):
        super().__init__(title, name, variants, layers, loopstart, loopend, blocksize, buffersize)

        v = variants if isinstance(variants, Sequence) else variants.values()
        l = () if layers is None else layers if isinstance(layers, Sequence) else layers.values()
        self._tracks = frozenset(itertools.chain(v, l))

        # TODO maybe ensure the tracks are compatible

        first = next(iter(v))
        self.sample_rate = lambda: first.samplerate
        self.file_length = lambda: first.frames
        self.channels = first.channels
    
    def sample_rate(self):
        ...
    
    def file_length(self):
        ...

    class Data(NamedTuple):
        variants: Mapping
        layers: Mapping

        def __len__(self):
            return len(next(iter(self.variants.values())))

    def _get_frames(self, block_size):
        data = MultiFileLoop.Data({}, {})
        for variant in self.variants():
            data.variants[variant] = self._variants[variant].read(block_size)
        for layer in self.layers():
            data.layers[layer] = self._layers[layer].read(block_size)
        self._position += block_size
        return data

    def seek(self, frames: int):
        for file in self._tracks:
            self._position = file.seek(frames)
    
    def _mix_data(self, data):
        parts = [data.variants[self._active_variant]]
        parts.extend(data.layers[lay] for lay in self._active_layers)
        return np.clip(sum(parts), -1.0, 1.0)
    
    def _concatenate(self, alpha, bravo):
        variants = {v: np.concatenate((a, b)) for v, a, b in zip(alpha.variants.keys(), alpha.variants.values(), bravo.variants.values())}
        layers = {l: np.concatenate((a, b)) for l, a, b in zip(
            alpha.layers.keys(), alpha.layers.values(), bravo.layers.values())}
        return MultiFileLoop.Data(variants, layers)

# Identical to open_loops, but returns None or a single loop rather than a list


def open_loop(
    filename: str,
    errhand: Callable = ...,
    buffersize: int = 20,
    blocksize: int = 2048
) -> Union[None, SongLoop, Sequence[SongLoop]]:
    loops = open_loops(filename, errhand, buffersize, blocksize)
    if len(loops) == 0:
        return None
    if len(loops) == 1:
        return loops[0]
    return loops

def open_loops(
    filename: str,
    errhand: Callable = ...,
    buffersize: int = 20,
    blocksize: int = 2048
) -> Sequence[SongLoop]:
    # try:
    dir = dirname(filename)
    if dir:
        dir += '/'
    name, ext = splitext(filename)
    if ext == '.json':
        file_list = json.load(open(filename, 'r'))
        if not isinstance(file_list, Sequence):
            file_list = [file_list]
    else:
        file_list = [{'filename': basename(filename), 'version': 2}]
    # except FileNotFoundError as e:
    #     if errhand is None:
    #         pass
    #     elif errhand is ...:
    #         print(e)
    #     else:
    #         errhand(file, e)
    #     return

    loops = []
    for info in file_list:
        try:
            # new version uses filename arg
            file = dir + info['filename']
        except KeyError:
            # old version assumed wav but might as well add support for other types
            varname = info['variants'][0]
            if varname:
                varname = '-' + varname
            file = name + varname + '.' + info.get('filetype', 'wav')
        meta = am.load(file)
        tags = meta['tags']

        try:
            loopstart = int(tags['loopstart'][0])
            loopend = loopstart + int(tags['looplength'][0])
        except (UnsupportedFormat, KeyError):
            loopstart = None
            loopend = None

        try:
            loopstart = info['loopstart']
            loopend = info['loopend']
        except KeyError:
            pass
            
        try:
            title = tags['title'][0]
        except KeyError:
            title = info.get('title', file)
        
        part_name = info.get('name', 'Play')

        version = info.get('version', 1)
        if version == 1:  # Classic style loop
            variants = {}
            for variant in info['variants']:
                var_name = '-' + variant if variant else ''
                variants[variant] = sf.SoundFile(
                    name + var_name + '.' + info.get('filetype', 'wav')
                )
            layers = {}
            for layer in info.get('layers', []):
                lay_name = '-' + layer if layer else ''
                layers[layer] = sf.SoundFile(
                    name + lay_name + '.' + info.get('filetype', 'wav')
                )
            loop = MultiFileLoop(
                title,
                part_name,
                variants,
                layers,
                loopstart,
                loopend,
                blocksize,
                buffersize
            )
        if version == 2:  # Monolithic loop
            file = sf.SoundFile(file)
            variants = info.get('variants', [0])
            layers = info.get('layers', range(1, file.channels // 2))
            loop = MultiTrackLoop(
                title,
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
        loops.append(loop)
    
    return loops


def main():
    try:
        song = open_loops('oggs/dolphin_shoals_n.ogg')[0]
        song.play()
    except KeyboardInterrupt:
        return


if __name__ == '__main__':
    main()

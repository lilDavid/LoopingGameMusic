import itertools
import json
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePath
from typing import Iterable, Iterator, NamedTuple, Optional, Union

import ffmpeg
import mutagen
import numpy as np
import requests
import soundfile as sf
from bs4 import BeautifulSoup
from babel.numbers import parse_number


class SongTrackURL(NamedTuple):
    name: str
    url: str


class Metadata(NamedTuple):
    """Metadata for a song to be downloaded, including loop data, sample rate,
    and tags."""

    title: str = None
    artist: Union[str, Sequence] = None
    album: str = None
    track_number: str = None
    year: str = None
    game: Union[str, Sequence] = None
    loop_start: int = None
    loop_end: int = None
    samplerate: int = None

    def override(self, base):
        """Return the union of this and the supplied Metadata object. Any fields
        shared between the two will have this object's value."""

        return Metadata(*(s or b for s, b in zip(self, base)))


class SongPart(NamedTuple):
    """A record of a song part to be downloaded."""

    name: str
    file: str
    meta: Metadata
    variants: Sequence[SongTrackURL]
    layers: Sequence[SongTrackURL]

    def iter_tracks(self) -> Iterator[SongTrackURL]:
        """Return an iterator over all of the tracks in this part."""

        return itertools.chain(self.variants, self.layers)

    def first_url(self):
        """Return the URL for the first track."""

        return next(self.iter_tracks()).url


def create_song(
    json_file: Union[str, PurePath],
    info: Union[SongPart, Iterable[SongPart]]
) -> None:
    """Download a song from SmashCustomMusic and save a JSON file about it to
    the given location."""

    json_path = Path(json_file)
    create_directory_for_file(json_path)
    parts = create_song_parts(json_path, info)
    parts = parts[0] if len(parts) == 1 else parts
    json.dump(parts, open(json_file, "w"))


def create_directory_for_file(file: Path) -> None:
    """Try to create one new directory level for the path.

    This function will only create up to one directory file. If the path is
    multiple nonexistent subdirectories deep, it will fail with a ValueError."""

    try:
        file.parent.mkdir(exist_ok=True)
    except FileNotFoundError as e:
        raise ValueError(
            f'Cannot automatically create more than one directory:\n{e.filename}'
        ) from e


def create_song_parts(
    file_path: PurePath,
    info: Union[SongPart, Iterable[SongPart]],
) -> Sequence[Mapping]:
    """Download the parts for a song and return information about said song.
    
    The returned sequence of mappings is in the format the looping program uses
    in its JSON files."""

    if isinstance(info, SongPart):
        return [create_part(file_path, info)]
    else:
        return [create_part(file_path, songinfo) for songinfo in info]


def create_part(
    file_path: PurePath,
    songinfo: SongPart
) -> Mapping:
    """Download one part of a song and return information about it.
    
    The returned mapping is in the format the program uses for its JSON data."""

    metadata = get_file_information(songinfo)

    variant_map, layer_map = download_and_convert_brstms(file_path, songinfo)
    files = list_track_files(file_path, variant_map, layer_map)

    song_file_path = create_multitrack_file(
        file_path,
        songinfo,
        metadata,
        files
    )
    add_metadata(metadata, song_file_path)

    return {
        "version": 2,
        "name": songinfo.name,
        "filename": songinfo.file,
        "variants": variant_map,
        "layers": layer_map
    }


def get_file_information(songpart: SongPart) -> Metadata:
    """Extract needed information on a song part from Smash Custom Music and
    return it as a Metadata tuple.
    
    In addition to the tags in the original SongPart's metadata field, the
    returned tuple will have the file's sample rate filled and may have its loop
    points and other tags filled if present on the song's page and not filled in
    the original metadata."""

    infotable = get_brstm_info_table(songpart.first_url())
    metadata = get_metadata_from_table(infotable)
    return songpart.meta.override(metadata)


def get_brstm_info_table(url: str) -> BeautifulSoup:
    """Open and return an HTML parser for the provided page (assumed to be on
    Smash Custom Music) and navigate it to the BRSTM info table.
    
    Said table contains metadata describing the song's format and loop
    information, as well as its title and game of origin."""

    soup = open_page(url)
    brstm_info = soup.find(id="prevsub")
    info = brstm_info.find(id="prevleft")
    info = info.find_all("td")
    return info


def open_page(url) -> BeautifulSoup:
    """Open an HTML parser for the provided page."""

    page = requests.get(url)
    soup = BeautifulSoup(page.content, "html.parser")
    return soup


def get_metadata_from_table(table: BeautifulSoup) -> Metadata:
    """Extract a song part's metadata from its table on Smash Custom Music.
    
    The returned Metadata tuple will have its sample rate, title, and game
    fields filled, and it may have the loop information and other tags filled
    if present in the table."""
    
    game = table[1].text.strip()
    title = table[3].text.strip()
    if table[31].text == 'Song Does Not Loop':
        loop_start = loop_end = None
    else:
        loop_start = parse_number(table[33].text, locale='en_US')
        loop_end = parse_number(table[35].text, locale='en_US')
    samplerate = int(table[37].text)

    return Metadata(
        title=title,
        game=game,
        loop_start=loop_start,
        loop_end=loop_end,
        samplerate=samplerate
    )


def download_and_convert_brstms(
    file_path: PurePath,
    songinfo: SongPart
) -> tuple[Mapping[str, int], ...]:
    """Download the BRSTM files for a song part and copy them into FLAC files.
    
    The returned tuple is a pair of mappings that map a track's name to the
    number of the FLAC file into which it was saved. The first is the part's 
    variants, the second its layers."""

    print('Downloading BRSTM files...')

    variants = download_tracks(file_path, songinfo.variants)
    layers = download_tracks(file_path, songinfo.layers, len(variants))

    return variants, layers


def download_tracks(
    file_path: PurePath,
    tracklist: Sequence[SongTrackURL],
    start: int = 0
) -> Mapping[str, int]:
    """Download a set of track BRSTMs and covert them into FLAC files.
    
    The returned mapping maps the tracks' names to the number of the file into
    which it was saved."""

    track_map = {}
    for i, track in enumerate(tracklist, start):
        soup = open_page(track.url)
        download_brstm(soup, file_path)
        convert_brstm(file_path, i)
        track_map[track.name] = i
    return track_map


def download_brstm(soup: BeautifulSoup, path: PurePath) -> None:
    """Download a BRSTM file and save it to a BRSTM file with the same name as
    the provided path."""

    soup = soup.find(id="brstmdl")
    soup = soup.find_all("a")[0]
    brstm_link = "https://web.archive.org/" + soup.attrs["href"]
    print("Downloading file: " + brstm_link)
    with requests.get(brstm_link, stream=True) as request:
        request.raise_for_status()

        with open(path.with_suffix('.brstm'), "wb") as file:
            for chunk in request.iter_content(chunk_size=8192):
                file.write(chunk)


def convert_brstm(path: Path, number: int) -> PurePath:
    """Convert a BRSTM file to a numbered FLAC file, and return the path to that
    file."""

    inpath = path.with_stem('.brstm')
    outpath = path.with_name(f'{path.stem}-{number}.flac')
    ffmpeg.input(str(inpath)).output(str(outpath)).run(overwrite_output=True)
    inpath.unlink()
    return outpath


def list_track_files(
    file_path: PurePath,
    *tracklists: Mapping[str, int]
) -> Sequence[sf.SoundFile]:
    """Chain the provided track mappings into a single list of SoundFiles for
    the files they originally pointed to."""

    tracklists = map(Mapping.values, tracklists)
    tracklist = itertools.chain.from_iterable(tracklists)
    return [sf.SoundFile(file_path.with_name(f'{file_path.stem}-{n}.flac')) for n in tracklist]


def create_multitrack_file(
    json_path: PurePath,
    songinfo: SongPart,
    metadata: Metadata,
    files: Iterable[sf.SoundFile]
) -> PurePath:
    """Create a final multi-track song part file and return the path to it."""

    song_path = json_path.parent / songinfo.file
    songfile = create_sound_file(song_path, songinfo, metadata.samplerate)
    merge_sound_files(files, songfile)
    lengthen_file_if_needed(metadata, files, songfile)
    close_files(files, songfile)
    
    return song_path


def create_sound_file(
    file_path: PurePath,
    songinfo: SongPart,
    samplerate: int
) -> sf.SoundFile:
    """Create a song part's sound file and return the file."""

    return sf.SoundFile(
        file_path,
        mode='w',
        samplerate=samplerate,
        channels=(len(songinfo.variants) + len(songinfo.layers)) * 2,
        format='OGG'
    )


def merge_sound_files(
    separate_files: Iterable[sf.SoundFile],
    single_file: sf.SoundFile
) -> None:
    """Copy the data from each of the separate sound files into the single
    sound file.
    
    The single file must have enough tracks to fit the data from all of the
    files at once."""

    datasize = 1
    chunk_size = 8192
    print('Copying audio data...')
    while datasize:
        datasize = copy_chunk(single_file, separate_files, chunk_size)


def lengthen_file_if_needed(
    metadata: Metadata,
    files: Iterable[sf.SoundFile],
    songfile: sf.SoundFile
) -> None:
    # Workaround to a problem where the file dies while
    # looping because it loses some data when seeking
    if songfile.frames - metadata.loop_end < 2048:
        print('Padding file at the end...')
        for file in files:
            file.seek(metadata.loop_start)
        copy_chunk(songfile, files, 2048)


def close_files(files_to_remove: Iterable[sf.SoundFile], file_to_not_remove: sf.SoundFile):
    """Close all files provided, and remove all of the files in the iterable."""

    for file in files_to_remove:
        file.close()
        Path(file.name).unlink()
    file_to_not_remove.close()


def copy_chunk(
    output_file: sf.SoundFile,
    input_files: Iterable[sf.SoundFile],
    size: int
) -> int:
    """Copy a chunk from each of the input files into the output file and return
    the amount of data copied.

    The amount of data copied will be less than or equal to the value of the
    the size parameter. If the input files are close to their end, then the
    function will copy all that's left; otherwise, *size* frames will be copied.
    
    The input file must have enough tracks to fit each of the output files."""

    data = read_chunk(output_file, input_files, size)
    output_file.write(data)
    output_file.flush()
    return len(data)


def read_chunk(
    output_file: sf.SoundFile,
    input_files: Iterable[sf.SoundFile],
    size: int
) -> np.ndarray:
    """Read chunk of *size* frames from each of the input files and stack them
    all into an array, and then return that array.
    
    The length of that array will be less than *size* if the input files are all
    read to their end; otherwise, it will be equal to *size*. The height will be
    the number of channels in the output file."""

    data = np.ndarray((size, output_file.channels), 'float64')
    maxlength = 0
    for i, file in enumerate(input_files):
        fileread = file.read(size)
        maxlength = max(maxlength, len(fileread))
        data[:len(fileread), 2*i:2*(i+1)] = fileread
    return data[:maxlength]


def add_metadata(metadata: Metadata, file_path: PurePath) -> None:
    """Add metadata to a sound file."""

    print('Metadata...')

    tags = mutagen.File(file_path)
    tags['title'] = [metadata.title]
    tags['artist'] = potential_single_string_to_list(metadata.artist)
    tags['game'] = potential_single_string_to_list(metadata.game)
    tags['loopstart'] = [str(metadata.loop_start)]
    tags['looplength'] = [str(metadata.loop_end - metadata.loop_start)]

    def default_padding(info):
        return info.get_default_padding()
    tags.save(padding=default_padding)


def potential_single_string_to_list(
    value: Union[str, Sequence[str], None]
) -> Optional[Sequence[str]]:
    """If the value is a string, wrap it in a list and return it. Otherwise, 
    return the value."""

    if isinstance(value, str):
        return [value]
    else:
        return value

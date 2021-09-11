import itertools
import json
import locale
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePath
from typing import Iterable, Iterator, NamedTuple, Union

import ffmpeg
import mutagen
import numpy as np
import requests
import soundfile as sf
from bs4 import BeautifulSoup


class SongVariantURL(NamedTuple):
    name: str
    url: str


class Metadata(NamedTuple):
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
        return Metadata(*(s or b for s, b in zip(self, base)))


class SongInfo(NamedTuple):
    name: str
    file: str
    meta: Metadata
    variants: Sequence[SongVariantURL]
    layers: Sequence[SongVariantURL]

    def iter_tracks(self) -> Iterator[SongVariantURL]:
        return itertools.chain(self.variants, self.layers)

    def first_url(self):
        return next(self.iter_tracks()).url


def create_song(
    json_file: Union[str, PurePath],
    info: Union[SongInfo, Iterable[SongInfo]]
) -> None:
    json_path = Path(json_file)
    create_directory_for_file(json_path)
    parts = create_song_parts(json_path, info)
    parts = parts[0] if len(parts) == 1 else parts
    json.dump(parts, open(json_file, "w"))


def create_directory_for_file(file: PurePath) -> None:
    try:
        Path(file).parent.mkdir(exist_ok=True)
    except FileNotFoundError as e:
        raise ValueError(
            'Cannot automatically create more than one directory:\n'
                + e.filename
        ) from e


def create_song_parts(
    file_path: PurePath,
    info: Union[SongInfo, Iterable[SongInfo]],
) -> Sequence[Mapping]:
    if isinstance(info, SongInfo):
        return [create_part(file_path, info)]
    else:
        return [create_part(file_path, songinfo) for songinfo in info]


def create_part(
    file_path: PurePath,
    songinfo: SongInfo
) -> Mapping:
    metadata = get_file_information(songinfo)

    variant_map, layer_map = download_and_convert_brstms(
        file_path,
        songinfo
    )
    files = list_track_filenames(file_path, variant_map, layer_map)

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


def get_file_information(songinfo: SongInfo) -> Metadata:
    infotable = get_brstm_info_table(songinfo.first_url())
    metadata = get_metadata_from_table(infotable)
    return songinfo.meta.override(metadata)


def get_brstm_info_table(url: str) -> BeautifulSoup:
    soup = open_page(url)

    brstm_info = soup.find(id="prevsub")
    info = brstm_info.find(id="prevleft")
    info = info.find_all("td")
    return info


def open_page(url) -> BeautifulSoup:
    page = requests.get(url)
    soup = BeautifulSoup(page.content, "html.parser")
    return soup


def get_metadata_from_table(table: BeautifulSoup) -> Metadata:
    prevloc = locale.getlocale(locale.LC_NUMERIC)
    locale.setlocale(locale.LC_NUMERIC, 'en_US.UTF-8')
    
    game = table[1].text.strip()
    title = table[3].text.strip()
    if table[31].text == 'Song Does Not Loop':
        loop_start = loop_end = None
    else:
        loop_start = locale.atoi(table[33].text)
        loop_end = locale.atoi(table[35].text)
    samplerate = int(table[37].text)

    locale.setlocale(locale.LC_NUMERIC, prevloc)
    return Metadata(
        title=title,
        game=game,
        loop_start=loop_start,
        loop_end=loop_end,
        samplerate=samplerate
    )


def download_and_convert_brstms(
    file_path: PurePath,
    songinfo: SongInfo
) -> tuple[Mapping, ...]:
    print('Downloading BRSTM files...')

    variants = download_tracks(file_path, songinfo.variants)
    layers = download_tracks(file_path, songinfo.layers, len(variants))

    return variants, layers


def download_tracks(
    file_path: PurePath,
    tracklist: Sequence[SongVariantURL],
    start: int = 0
) -> Mapping[str, int]:
    track_map = {}
    for i, track in enumerate(tracklist, start):
        soup = open_page(track.url)
        download_brstm(soup, file_path)
        convert_brstm(file_path, i)
        track_map[track.name] = i
    return track_map


def download_brstm(soup: BeautifulSoup, path: PurePath) -> None:
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
    inpath = path.with_stem('.brstm')
    outpath = path.with_name(f'{path.stem}-{number}.flac')
    ffmpeg.input(str(inpath)).output(str(outpath)).run(overwrite_output=True)
    inpath.unlink()
    return outpath


def list_track_filenames(
    file_path: PurePath,
    *tracklists: Mapping[str, int]
) -> Sequence[sf.SoundFile]:
    tracklists = map(Mapping.values, tracklists)
    tracklist = itertools.chain.from_iterable(tracklists)
    return [sf.SoundFile(file_path.with_name(f'{file_path.stem}-{n}.flac')) for n in tracklist]


def create_multitrack_file(
    json_path: PurePath,
    songinfo: SongInfo,
    metadata: Metadata,
    files: Iterable[sf.SoundFile]
) -> PurePath:
    song_path = json_path.parent / songinfo.file
    songfile = create_sound_file(song_path, songinfo, metadata.samplerate)
    merge_sound_files(files, songfile)
    lengthen_file_if_needed(metadata, files, songfile)
    close_files(files, songfile)
    
    return song_path


def create_sound_file(
    file_path: PurePath,
    songinfo: SongInfo,
    samplerate: int
) -> sf.SoundFile:
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
    for file in files_to_remove:
        file.close()
        Path(file.name).unlink()
    file_to_not_remove.close()


def copy_chunk(
    output_file: sf.SoundFile,
    input_files: Iterable[sf.SoundFile],
    size: int
) -> None:
    data = read_chunk(output_file, input_files, size)
    output_file.write(data)
    output_file.flush()
    return len(data)


def read_chunk(
    output_file: sf.SoundFile,
    input_files: Iterable[sf.SoundFile],
    size: int
) -> np.ndarray:
    data = np.ndarray((size, output_file.channels), 'float64')
    maxlength = 0
    for i, file in enumerate(input_files):
        fileread = file.read(size)
        maxlength = max(maxlength, len(fileread))
        data[:len(fileread), 2*i:2*(i+1)] = fileread
    return data[:maxlength]


def add_metadata(metadata: Metadata, file_path: PurePath) -> None:
    print('Metadata...')

    tags = mutagen.File(file_path)
    tags['title'] = [metadata.title]
    set_potential_multiple_tag(tags, 'artist', metadata.artist)
    set_potential_multiple_tag(tags, 'game', metadata.game)
    tags['loopstart'] = [str(metadata.loop_start)]
    tags['looplength'] = [str(metadata.loop_end - metadata.loop_start)]

    def default_padding(info):
        return info.get_default_padding()
    tags.save(padding=default_padding)


def set_potential_multiple_tag(tags, tag_name: str, tag_value: Sequence):
    if isinstance(tag_value, str):
        tags[tag_name] = [tag_value]
    elif tag_value is not None:
        tags[tag_name] = tag_value


def main():
    # TODO: Rework into a wizard rather than argv spam

    if len(sys.argv) < 3:
        print(
            "Rips a WAV file from a BRSTM from the archive of SmashCustomMusic.",
            f"Usage: {sys.argv[0]} <filename to use, no extension or spaces>",
            "[-variant name, no spaces] <link to page> [-<variant name>",
            "<link to another page>]... --layers ...",
            end="\n"
        )
        return

    local_filename = sys.argv[1]
    variants = []
    layers = []
    if sys.argv[2][0] == '-' and len(sys.argv[2]) != 1:
        variants.append(SongVariantURL(sys.argv[2], sys.argv[3]))
        named_start = True
    else:
        variants.append(SongVariantURL("", sys.argv[2]))
        named_start = False

    try:
        argv = iter(sys.argv[4 if named_start else 3:])
        item = next(argv)
        while item != "--layers":
            if len(item) == 1:
                print("Variant name must be at least 1 character excluding dash")
                return
            variants.append(SongVariantURL(item, next(argv)))
            item = next(argv)
        for item in argv:
            if len(item) == 1:
                print("Variant name must be at least 1 character excluding dash")
                return
            layers.append(SongVariantURL(item, next(argv)))
    except StopIteration:
        pass

    file = create_song_parts(local_filename, SongInfo("", variants, layers))
    file["name"] = input(
        "Enter VGM title (leave blank to use file name): ") # or os.path.basename(local_filename)
    json.dump(
        file,
        open(local_filename + ".json", "wt")
    )


if __name__ == "__main__":
    main()

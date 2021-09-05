import json
import locale
import os
import sys
from collections.abc import Sequence, Mapping
from typing import Iterable, NamedTuple, Union
import itertools

import ffmpeg
import mutagen
import numpy as np
import requests
import soundfile as sf
from bs4 import BeautifulSoup


class SongVariantURL(NamedTuple):
    name: str
    url: str


class SongInfo(NamedTuple):
    name: str
    title: str
    file: str
    variants: Sequence[SongVariantURL]
    layers: Sequence[SongVariantURL]


class Metadata(NamedTuple):
    title: str = None
    loop_start: int = None
    loop_end: int = None
    samplerate: int = None


Filename = str


def create_song(
    json_file: Filename,
    info: Union[SongInfo, Iterable[SongInfo]]
) -> None:
    parts = create_song_parts(os.path.splitext(json_file)[0], info)
    parts = parts[0] if len(parts) == 1 else parts
    json.dump(parts, open(json_file, "w"))


def create_song_parts(
    local_filename: Filename,
    info: Union[SongInfo, Iterable[SongInfo]]
) -> Sequence[Mapping]:
    if isinstance(info, SongInfo):
        return [create_part(local_filename, info)]
    else:
        return [create_part(local_filename, songinfo) for songinfo in info]


def create_part(local_filename: Filename, songinfo: SongInfo) -> Mapping:
    metadata = get_file_information(songinfo, Metadata(title=songinfo.title))
    variant_map, layer_map = download_and_convert_brstms(
        local_filename, songinfo)
    files = list_filenames(variant_map, layer_map)
    filename = create_multitrack_file(
        local_filename, songinfo, metadata, files)
    add_metadata(metadata, filename)
    return {
        "version": 2,
        "name": songinfo.name,
        "filename": songinfo.file,
        "variants": variant_map,
        "layers": layer_map
    }


def get_file_information(songinfo: SongInfo, overrides: Metadata) -> Metadata:
    page = requests.get(songinfo.variants[0].url)
    soup = BeautifulSoup(page.content, "html.parser")
    brstm_info = soup.find(id="prevsub")

    info = brstm_info.find(id="prevleft")
    info = info.find_all("td")

    prevloc = locale.getlocale(locale.LC_NUMERIC)
    locale.setlocale(locale.LC_NUMERIC, 'en_US.UTF-8')
    loop_start = locale.atoi(info[33].text)
    loop_end = locale.atoi(info[35].text)
    samplerate = int(info[37].text)
    locale.setlocale(locale.LC_NUMERIC, prevloc)
    return Metadata(overrides.title, loop_start, loop_end, samplerate)


def download_and_convert_brstms(
    file_basename: Filename,
    songinfo: SongInfo
) -> tuple[Mapping, ...]:
    print('Downloading BRSTM files...')

    variant_map = download_tracks(file_basename, songinfo.variants)
    layer_map = download_tracks(file_basename, songinfo.layers)

    return variant_map, layer_map


def download_tracks(
    file_basename: Filename,
    tracklist: Sequence[SongVariantURL]
) -> Mapping[str, Filename]:
    track_map = {}
    for i, track in enumerate(tracklist):
        soup = open_page(track.url)
        download_brstm(soup, file_basename)
        track_map[track.name] = convert_brstm(file_basename, i)
    return track_map


def open_page(url) -> BeautifulSoup:
    page = requests.get(url)
    soup = BeautifulSoup(page.content, "html.parser")
    return soup


def download_brstm(soup: BeautifulSoup, filename: Filename) -> None:
    soup = soup.find(id="brstmdl")
    soup = soup.find_all("a")[0]
    brstm_link = "https://web.archive.org/" + soup.attrs["href"]
    print("Downloading file: " + brstm_link)
    with requests.get(brstm_link, stream=True) as request:
        request.raise_for_status()

        with open(f'{filename}.brstm', "wb") as file:
            for chunk in request.iter_content(chunk_size=8192):
                file.write(chunk)


def convert_brstm(filename: Filename, number: int) -> Filename:
    infile = f'{filename}.brstm'
    outfile = f'{filename}-{number}.flac'
    ffmpeg.input(infile).output(outfile).run(overwrite_output=True)
    os.remove(infile)
    return outfile


def list_filenames(
    *tracklists: Mapping[str, Filename]
) -> Sequence[sf.SoundFile]:
    filenames = map(Mapping.values, tracklists)
    tracklist = itertools.chain.from_iterable(filenames)
    return [sf.SoundFile(filename) for filename in tracklist]


def create_multitrack_file(
    local_filename: Filename,
    songinfo: SongInfo,
    metadata: Metadata,
    files: Iterable[sf.SoundFile]
) -> Filename:
    songfile = create_sound_file(local_filename, songinfo, metadata.samplerate)
    individual_files_to_one(files, songfile)
    lengthen_file_if_needed(metadata, files, songfile)
    for file in files:
        file.close()
        os.remove(file.name)
    songfile.close()
    
    return songfile.name


def create_sound_file(
    local_filename: Filename,
    songinfo: SongInfo,
    samplerate: int
) -> sf.SoundFile:
    directory = os.path.dirname(local_filename)
    if directory:
        directory += '/'

    return sf.SoundFile(
        directory + songinfo.file,
        mode='w',
        samplerate=samplerate,
        channels=(len(songinfo.variants) + len(songinfo.layers)) * 2,
        format='OGG'
    )


def individual_files_to_one(
    files: Iterable[sf.SoundFile],
    songfile: sf.SoundFile
) -> None:
    data = 'a'
    chunk_size = 8192
    print('Copying audio data...')
    while len(data):
        data = read_chunk(songfile, files, chunk_size)
        songfile.write(data)
        songfile.flush()


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
        songfile.write(read_chunk(songfile, files, 2048))
        songfile.flush()


def read_chunk(
    infile: sf.SoundFile,
    outfiles: Iterable[sf.SoundFile],
    size: int
) -> np.ndarray:
    data = np.ndarray((size, infile.channels), 'float64')
    maxlength = 0
    for i, file in enumerate(outfiles):
        fileread = file.read(size)
        maxlength = max(maxlength, len(fileread))
        data[:len(fileread), 2*i:2*(i+1)] = fileread
    return data[:maxlength]


def add_metadata(metadata: Metadata, filename: Filename) -> None:
    print('Metadata...')

    tags = mutagen.File(filename)
    tags['title'] = [metadata.title]
    tags['loopstart'] = [str(metadata.loop_start)]
    tags['looplength'] = [str(metadata.loop_end - metadata.loop_start)]

    def default_padding(info):
        return info.get_default_padding()
    tags.save(padding=default_padding)


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
        "Enter VGM title (leave blank to use file name): ") or os.path.basename(local_filename)
    json.dump(
        file,
        open(local_filename + ".json", "wt")
    )


if __name__ == "__main__":
    main()

import json
import locale
import os
import sys
from collections.abc import Sequence
from typing import Callable, Iterable, NamedTuple, Union

import ffmpeg
import mutagen
import numpy as np
import requests
import soundfile as sf
from bs4 import BeautifulSoup
from requests import HTTPError


class SongVariantURL(NamedTuple):
    name: str
    url: str


class SongInfo(NamedTuple):
    name: str
    title: str
    file: str
    variants: Sequence[SongVariantURL]
    layers: Sequence[SongVariantURL]


def get_brstms(
    local_filename: str,
    info: Union[SongInfo, Sequence[SongInfo]],
    logout=sys.stdout,
    err_handle: Callable = ...
) -> dict:
    if err_handle is None:
        def ignore(*_):
            pass
        err_handle = ignore
    if err_handle is Ellipsis:
        def default_handle(e, link, *_):
            print("Could not download", link, e)
        err_handle = default_handle
    
    if isinstance(info, SongInfo):
        info = [info]
    songs = []

    for songinfo in info:
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
        
        dirname = os.path.dirname(local_filename)
        if dirname:
            dirname += '/'

        songfile = sf.SoundFile(
            dirname + songinfo.file,
            mode='w',
            samplerate=samplerate,
            channels=(len(songinfo.variants) + len(songinfo.layers)) * 2,
            format='OGG'
        )

        def download_brstm(soup: BeautifulSoup, number: int):
            soup = soup.find(id="brstmdl")
            soup = soup.find_all("a")[0]
            brstm_link = "https://web.archive.org/" + soup.attrs["href"]
            print("Downloading file: " + brstm_link, file=logout)
            with requests.get(brstm_link, stream=True) as request:
                try:
                    request.raise_for_status()
                except HTTPError as e:
                    err_handle(e, brstm_link)
                    return

                brstm_filename = f'{local_filename}-{number}'

                with open(brstm_filename + '.brstm', "wb") as file:
                    for chunk in request.iter_content(chunk_size=8192):
                        file.write(chunk)
                try:
                    ffmpeg.input(brstm_filename + '.brstm').output(
                        brstm_filename + '.flac').run(overwrite_output=True)
                except ffmpeg.Error as e:
                    err_handle(e, brstm_link)
        
        print('Downloading BRSTM files...')

        variant_map = {}
        for i, variant in enumerate(songinfo.variants):
            page = requests.get(variant.url)
            soup = BeautifulSoup(page.content, "html.parser")
            download_brstm(soup, i)
            variant_map[variant.name] = i

        layer_map = {}
        for i, layer in enumerate(songinfo.layers):
            page = requests.get(layer.url)
            soup = BeautifulSoup(page.content, "html.parser")
            download_brstm(soup, i)
            layer_map[layer.name] = i

        files: list[sf.SoundFile] = []
        for i in range(songfile.channels // 2):
            files.append(sf.SoundFile(f'{local_filename}-{i}.flac'))

        def read_chunk(
            infile: sf.SoundFile,
            outfiles: Iterable[sf.SoundFile],
            size: int
        ):
            data = np.ndarray((size, infile.channels), 'float64')
            maxlength = 0
            for i, file in enumerate(outfiles):
                fileread = file.read(size)
                maxlength = max(maxlength, len(fileread))
                data[:len(fileread), 2*i:2*(i+1)] = fileread
            return data[:maxlength]

        data = 'a'
        chunk_size = 8192
        print('Copying audio data...')
        while len(data):
            data = read_chunk(songfile, files, chunk_size)
            songfile.write(data)
            songfile.flush()

        # Workaround to a problem where the file dies while
        # looping because it loses some data when seeking
        if songfile.frames - loop_end < 2048:
            print('Padding file at the end...')
            for file in files:
                file.seek(loop_start)
            songfile.write(read_chunk(songfile, files, 2048))
            songfile.flush()

        songfile.close()

        for i in range(songfile.channels // 2):
            os.remove(f'{local_filename}-{i}.brstm')
            os.remove(f'{local_filename}-{i}.flac')

        print('Metadata...')

        tags = mutagen.File(dirname + songinfo.file)
        tags['title'] = [songinfo.title]
        tags['loopstart'] = [str(loop_start)]
        tags['looplength'] = [str(loop_end - loop_start)]
        def default_padding(info):
            return info.get_default_padding()
        tags.save(padding=default_padding)

        songs.append({
            "version": 2,
            "name": songinfo.name,
            "filename": songinfo.file,
            "variants": variant_map,
            "layers": layer_map
        })
    
    if len(songs) == 1:
        return songs[0]
    else:
        return songs


def main():
    # TODO: Rework into a wizard rather than argv spam

    if len(sys.argv) < 3:
        print(
            "Rips a WAV file from a BRSTM from the archive of SmashCustomMusic.",
            f"Usage: {sys.argv[0]} <filename to use, no extension or spaces> [-variant name, no spaces] <link to page> [-<variant name> <link to another page>]... --layers ...",
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

    file = get_brstms(local_filename, SongInfo("", variants, layers))
    file["name"] = input(
        "Enter VGM title (leave blank to use file name): ") or os.path.basename(local_filename)
    json.dump(
        file,
        open(local_filename + ".json", "wt")
    )


if __name__ == "__main__":
    main()

import json
import locale
import os
import sys
from collections import namedtuple
from collections.abc import Sequence
from typing import Callable, Union

import ffmpeg
import requests
from bs4 import BeautifulSoup
from requests import HTTPError

SongVariantURL = namedtuple('SongVariantURL', ['name', 'url'])


NamedSongInfo = namedtuple('NamedSongInfo', ['name', 'variants', 'layers'])
TitledSongInfo = namedtuple('TitledSongInfo', ['name', 'title', 'variants', 'layers'])


def get_brstms(
    local_filename: str,
    # variants: Sequence[SongVariantURL],
    # layers: Sequence[SongVariantURL],
    info: Union[NamedSongInfo, TitledSongInfo, Sequence],
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
    
    if isinstance(info, tuple):
        info = [info]
    songs = []

    for songinfo in info:
        if len(songinfo) == 3:
            title, variants, layers = songinfo
            name = os.path.basename(local_filename)
        else:
            name, title, variants, layers = songinfo

        page = requests.get(variants[0].url)
        soup = BeautifulSoup(page.content, "html.parser")
        brstm_info = soup.find(id="prevsub")

        info = brstm_info.find(id="prevleft")
        info = info.find_all("td")

        prevloc = locale.getlocale(locale.LC_NUMERIC)
        locale.setlocale(locale.LC_NUMERIC, 'en_US.UTF-8')
        loop_start = locale.atoi(info[33].text)
        loop_end = locale.atoi(info[35].text)
        locale.setlocale(locale.LC_NUMERIC, prevloc)
        
        brstm_filename = local_filename + ".brstm"

        def download_brstm(soup: BeautifulSoup, variant: str = ""):
            soup = soup.find(id="brstmdl")
            soup = soup.find_all("a")[0]
            brstm_link = "https://web.archive.org/" + soup.attrs["href"]
            print("Downloading file: " + brstm_link, file=logout)
            with requests.get(brstm_link, stream=True) as request:
                try:
                    request.raise_for_status()
                except HTTPError as e:
                    err_handle(e, brstm_link)

                with open(brstm_filename, "wb") as file:
                    for chunk in request.iter_content(chunk_size=8192):
                        file.write(chunk)
                try:
                    ffmpeg.input(brstm_filename).output(
                        local_filename + variant + ".wav").run(overwrite_output=True)
                except ffmpeg.Error as e:
                    err_handle(e, brstm_link)

        try:
            for variant in variants:
                page = requests.get(variant.url)
                soup = BeautifulSoup(page.content, "html.parser")
                download_brstm(soup, variant.name)
            for layer in layers:
                page = requests.get(layer.url)
                soup = BeautifulSoup(page.content, "html.parser")
                download_brstm(soup, layer.name)
        except StopIteration:
            pass
        finally:
            os.remove(brstm_filename)

        songs.append({
            "name": name,
            "title": title,
            "variants": list(v.name[1:] for v in variants),
            "layers": list(l.name[1:] for l in layers),
            "loopstart": loop_start,
            "loopend": loop_end
        })
    if len(songs) == 1:
        return songs[0]
    else:
        return songs


def main():
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

    file = get_brstms(local_filename, NamedSongInfo("", variants, layers))
    file["name"] = input(
        "Enter VGM title (leave blank to use file name): ") or os.path.basename(local_filename)
    json.dump(
        file,
        open(local_filename + ".json", "wt")
    )


if __name__ == "__main__":
    main()

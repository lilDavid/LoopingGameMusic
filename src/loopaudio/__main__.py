import sys
from loopaudio import open_song

try:
    file = sys.argv[1]
    song = open_song(file)
    index = 0
    part = song.get_song(index)
    if not part.variants():
        part.set_layers_from_bits(1)
    song.play(index)
except IndexError:
    print(f'Usage: {sys.argv[0]} path/to/ogg/or/json')
except KeyboardInterrupt:
    pass
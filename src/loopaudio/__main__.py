import sys
from loopaudio import open_loops

try:
    file = sys.argv[1]
    song = open_loops(file)[0]
    if not song.variants():
        song.set_layers_from_bits(1)
    song.play()
except IndexError:
    print(f'Usage: {sys.argv[0]} path/to/ogg/or/json')
except KeyboardInterrupt:
    pass

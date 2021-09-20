import sys
from loopaudio import open_song

try:
	try:
		file = sys.argv[1]
	except IndexError:
		file = 'examples/dolphin_shoals_n.ogg'
	song = open_song(file)
	index = 0
	part = song.get_song(index)
	if not part.variants():
		part.set_layers_from_bits(1)
	song.play(index)
except KeyboardInterrupt:
	pass

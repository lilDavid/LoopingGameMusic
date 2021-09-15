import sys
from loopaudio import open_loops

try:
	try:
		file = sys.argv[1]
	except IndexError:
		file = 'examples/dolphin_shoals_n.ogg'
	song = open_loops(file)[0]
	if not song.variants():
		song.set_layers_from_bits(1)
	song.play()
except KeyboardInterrupt:
	pass

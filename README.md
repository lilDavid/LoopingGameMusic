# LoopingGameMusic

A music player that can play video game music that loops continuously. Also supports songs with multiple parts as well as variable mixing.

## Dependencies
- `SoundFile`
- `requests`
- `mutagen`
- `ffmpeg-python`
- `numpy`
- `sounddevice`
- `beautifulsoup4`

## Using
Navigate to the top level directory, then:
- To simply play a song: `python`/`python3 -m loopaudio path/to/file/or/json`
- For the GUI: `python`/`python3 -m loopaudio.gui`

### Player
When you open the player, your first step is the 'File' pane. You can open any compatible file after selecting it or entering its location relative to the current working directory (the folder opened when pressing the 'Pick file' button). Compatible files include probably most audio file types (OGG is the only type I've tested) or a JSON file describing the relationship between several files—more on that later.

When pressing the 'Load' button, one or more options just below the file selector will appear with the song's parts. Each part is a separate loop, and the current part can be changed at any time. When selecting a part, it will start playing immediately and populate the 'Variants' and 'Layers' panels. In those panels, you can select which variant to play as well as which layers (if any) to play on top. These variants and layers can be changed on the fly as the song plays to emulate the dynamic mixing some games employ. The slider below the variants and layers will change the volume of the song. To stop playback, you can press the 'Stop' button next to the part buttons, or you may select a different part's button to immediately start playing it instead.

### Smash Custom Music archive
You can press the button at the very bottom of the window to open the GUI to import BRSTM files from [the archive of Smash Custom Music](https://web.archive.org/web/20190619095108/https://www.smashcustommusic.com/gamelist) as playable songs. From there you can start again with the 'File' panel by entering a path for a JSON file for the song's data. The next row contains both the 'Start conversion' button and a 'Use JSON' checkbox. The latter doesn't do anything yet.

The tabbed pane is where you manage each part of the song. If your song only has one part to it—that is, there's only one loop associated with it and it isn't meant to transition to something else—you can ignore the 'Manage parts' tab. Otherwise, that's where you can add and remove tabs and by extension parts to your song.

The 'Information' panel contains basic facts about the song, including its title, the name of the part (optional if there's only one part) and the filename of the actual file to save the audio data. This filename is relative to the directory of the JSON file, so if the files will be in a nested directory start it with either the subdirectory's name or a dot; otherwise, just write the filename.

The 'Variants' and 'Layers' panels are where the magic happens. Just name each variant or layer in the left column and link its page (not the file itself) in the right. The import wizard web-scrapes to get the information it needs, so using any page other than a Smash Custom Music page [like this one](https://web.archive.org/web/20190617173638/https://www.smashcustommusic.com/45669) will almost certainly break it.

Finally, just press the 'Start conversion' button at the top and the program should import the song as one JSON file and at least one audio file.

### Playing Programatically

You can also import loopaudio as a module in order to play these loops. The main entry point for that is the loopaudio.open_loop() and loopaudio.open_loops() functions (the difference the former returns a single SongLoop object if it only reads one, whereas the latter always returns a list of SongLoops). No docstrings for that yet, but I'll get around to it eventually; at least there are type hints.

## File format

As mentioned before, the Loop GUI opens either a single audio file or a JSON file that joins together several such files. The details of such are as follows:

### Audio files
The only formatting an audio file needs in order to loop in this program is the LOOPSTART and LOOPLENGTH metadata tags. The program internally uses the end loop point rather than the length, but length is used in the file because (apparently) RPG Maker does the same. Anyway, the Title tag is also used to display the name of the song, although it can work fine without. For variable mixing to work, the song simply needs more than two audio tracks, though currently the number of tracks must also be even. Opening the sound file directly in the program will read all of those pairs as layers, but if you write a JSON file describing the song, you can get the proper variants and layers as well as their names when opened in the GUI.

### JSON files
The real meat that this program runs on is JSON files describing the loops. A typical file with multiple parts and mixes may look like this one:
```json
[
	{
		"version": 2,
		"name": "Normal",
		"filename": "dolphin_shoals_n.ogg",
		"variants": {
			"Shallow water": 0,
			"Deep water": 2,
			"Above water": 3
		},
		"layers": {
			"Frontrunning": 1
		}
	},
	{
		"version": 2,
		"name": "Final lap",
		"filename": "dolphin_shoals_f.ogg",
		"variants": {
			"Main track": 0
		},
		"layers": {
			"Frontrunning": 1
		}
	},
	{
		"version": 2,
		"name": "Highlight Reel",
		"filename": "dolphin_shoals_h.ogg",
		"variants": {
			"Main track": 0
		}
	}
]
```
The breakdown of which is as follows.

#### Top level
This will be either a single object describing one part, or a list of the same to make multiple parts.

#### Part data
- **version**: The version of the reader to use. For the foreseeable future this will be 2, as 1 was obsolete before I published this on GitHub.
- **name**: The name for this part. Separate from the title, it should be short and descriptive of its relation to the whole song. If the song only has one part, you don't need to specify this, but it would be a good idea if it has multiple.
- **title**: The title of the song. Overrides the file's Title tag if it has one, but if neither is specified the player will display the filename.
- ••filename**: The location of the file relative to this JSON file.
- **variants**: Names for the song's variants and which **pair** of channels it's for. So in the case of the first "Normal" part, "Shallow water" is the first and second channels, "Deep water" is the fifth and sixth, and "Above water" is the seventh and eigth.
- **layers**: Same as above for the song's layers. If absent, the song will default to having no layers and only some number of variants—see the third part "Highlight Reel".

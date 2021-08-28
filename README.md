# LoopingGameMusic

A music player that can play video game music that loops continuously. Also supports songs with multiple parts as well as variable mixing.

## Using
The file to use as the main module is loop_gui.py. From there you can access both the player and the Smash Custom Music import feature. You *can* also run get_brstm.py, but currently the entry point for that file is broken and will be fixed at a later date.

### Player
When you open the player, your first step is the 'File' pane. You can open any compatible file after selecting it or entering its location relative to the current working directory (the folder opened when pressing the 'Pick file' button). Compatible files include probably most audio file types (OGG is the only type I've tested) or a JSON file describing the relationship between several files—more on that later.

When pressing the 'Load' button, one or more options just below the file selector will appear with the song's parts. Each part is a separate loop, and the current part can be changed at any time. When selecting a part, it will start playing immediately and populate the 'Variants' and 'Layers' panels. In those panels, you can select which variant to play as well as which layers (if any) to play on top. These variants and layers can be changed on the fly as the song plays to emulate the dynamic mixing some games employ. The slider below the variants and layers will change the volume of the song. To stop playback, you can press the 'Stop' button next to the file name, or you may select a different part's button to immediately start playing it instead.

### Smash Custom Music archive
You can press the button at the very bottom of the window to open the GUI to import BRSTM files from [the archive of Smash Custom Music](https://web.archive.org/web/20190619095108/https://www.smashcustommusic.com/gamelist) as playable songs. From there you can start again with the 'File' panel by entering a path for a JSON file for the song's data. The only relevant button on the second row of this panel is 'Start conversion;' nothing else there does anything yet.

The tabbed pane is where you manage each part of the song. If your song only has one part to it—that is, there's only one loop associated with it and it isn't meant to transition to something else—you can ignore the 'Manage parts' tab. Otherwise, that's where you can add and remove tabs and by extension parts to your song.

The 'Information' panel contains basic facts about the song, including its title, the name of the part (optional if there's only one part) and the filename of the actual file to save the audio data. This filename is relative to the directory of the JSON file, so if the files will be in a nested directory start it with either the subdirectory's name or a dot; otherwise, just write the filename.

The 'Variants' and 'Layers' panels are where the magic happens. Just name each variant or layer in the left column and link its page (not the file itself) in the right. The import wizard web-scrapes to get the information it needs, so using any page other than a Smash Custom Music page [like this one](https://web.archive.org/web/20190617173638/https://www.smashcustommusic.com/45669) will almost certainly break it.

Finally, just press the 'Start conversion' button at the top and the program should import the song as one JSON file and at least one audio file.

### Playing Programatically

You can also import loopaudio as a module in order to play these loops. The main entry point for that is the loopaudio.open_loop() and loopaudio.open_loops() functions (the difference the former returns a single SongLoop object if it only reads one, whereas the latter always returns a list of SongLoops). No docstrings for that yet, but I'll get around to it eventually; at least there are type hints.

## File format

As mentioned before, the Loop GUI opens either a single audio file or a JSON file that joins together several such files. The details of such are as follows:

### Audio files

...

### JSON files

...

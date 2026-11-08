# RX-7 and RX-8 high-rev warning

The RX-7 FD3S and FC3S and the RX-8 SE3P share the original arcade's `data/sound/race_se/rx7_rev1.wav`. The mixer plays this separate voice at 22000 Hz when the native high-rev envelope is active.

Android's original ZIP or directory conversion copies and verifies this file as `sound/rx7_rev1.wav`. The two supported older prepared data inventories omit it. Select the original ZIP or directory conversion to get the sample while keeping the separate save directory. For local development, `prepare_sound.sh` copies the same WAV from the arcade root into the runtime sound directory.

The game must call `snd_rev_quiet()` whenever physics/audio updates are suspended, including frozen scenes and closed versus sessions; `snd_quiet()` also silences it. This wiring is required; there is no automatic timeout.

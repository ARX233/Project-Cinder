<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/%E8%AF%AD%E8%A8%80-%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-lightgrey?style=for-the-badge" alt="简体中文"></a>
  <a href="README.en.md"><img src="https://img.shields.io/badge/Language-English-brightgreen?style=for-the-badge" alt="English"></a>
</p>

# Project Cinder

> An Android launcher and runtime for a classic arcade racing game.

Project Cinder puts an arcade racing cabinet on your phone — not as an emulator, and not as a streamed video. The launcher, the resource pipeline, the renderer and the input layer are written for Android, and the game runs on a native ARM64 runtime built for this project.

You bring your own game data. Cinder imports it locally, verifies the result, and runs it. Nothing is bundled, and nothing is downloaded from us.

## Status

Cinder is in active development. Builds are shipped as test versions and the online services are live but still being tuned.

- Single player, time attack and ghost battles work end to end.
- Some lighting and effects are approximations rather than exact reproductions.
- Behaviour varies noticeably between devices; low-end phones are still being tuned.
- Every build is run on real hardware before it is published, but that does not guarantee it works on yours.

If something breaks, please open an issue with the device model, Android version and what you were doing.

## Highlights

**Launcher**

- Landscape launcher with an explicit, gated launch — nothing starts on its own.
- Import your own game data from a ZIP or a directory, converted on the device.
- Converted output is verified before it is adopted, then swapped in atomically.
- Resources, garage saves, time attack records and ghost data are stored independently: clearing resources never clears your saves.

**Driving**

- Native ARM64 runtime with Vulkan and GLES render paths.
- Fixed 60 Hz simulation step — a dropped frame does not change how the car behaves.
- Touch, tilt steering and gamepad input, with a configurable layout per device.
- Engine audio, BGM and course lighting.

**Online**

- A device ID generated per install, authorized from a web page in one step.
- A time attack leaderboard, one board per course.
- A store ghost king per course, replaced by whoever beats it.
- Ghost sharing: upload a run, download someone else's car and race it.

## Online services

| Service | What it does |
| --- | --- |
| Device authorization | Register a device ID and the cloud starts working immediately |
| Time attack board | Fastest accepted run per driver, per course |
| Ghost king | The reigning ghost of each course — beat it and it is yours |
| Ghost sharing | Upload and download ghost containers |

Service home: <https://niceapi.net>

The board is a community board. Runs are checked for format and rule consistency on the server, but they are not replay-verified yet, and the site says so.

## Repository layout

| Path | Contents |
| --- | --- |
| `ports/android/` | Current Android sources: launcher, runtime, cloud service |
| `ports/ipad/` | Earlier experimental iOS port |
| `src/` | Runtime and game logic |
| `tools/` | Resource conversion, data extraction and build tooling |
| `android/` | Android packaging project |
| `docs/` | Design and verification notes |
| `build_android.sh` | Build entry point |

Each platform directory is its own development tree and should not overwrite the others. The repository root keeps the upstream baseline.

## Building

Requirements:

- Android SDK 36 and build-tools 36
- NDK 28
- JDK 17 or newer (recommended)
- Python 3.11+

The build takes an Android signing keystore, a resource baseline inventory and a runtime package as explicit inputs. Nothing is installed or uploaded by the build itself.

Some generated, game-derived files are deliberately not committed. A clean checkout will not compile until they are produced locally from data you supply. See [`ports/android/README.md`](ports/android/README.md) for the platform specifics.

## Credits

This project builds on the earlier MIT-licensed port published by [Allannn-sudo (高橋涼介のFC)](https://github.com/Allannn-sudo); their copyright notice is retained in [LICENSE](LICENSE).

## License and legal

The launcher source is MIT licensed.

Game material is **not** included, not licensed and not distributed by this repository. You must supply your own data and have the right to use it. Project Cinder is an independent hobby project; it is not affiliated with, endorsed by or sponsored by any game publisher or arcade manufacturer, and it ships no assets owned by one.

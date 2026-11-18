SCRIPT_METADATA = {
    "name": "common/music/organize_flac",
    "display_name": "Organize FLAC Music",
    "description": "Organize FLAC files into album folders using their tags.",
    "category": "Music",
    "tags": ["audio", "flac", "organize"],
    "platforms": ["common"],
    "execution": {
        "modes": {"allowed": ["inproc"], "default": "inproc"},
    },
    "params": [
        {
            "name": "source_dir",
            "label": "Source Folder",
            "type": "remote_folder",
            "required": True,
            "description": "Scan this folder and its subfolders.",
        },
        {
            "name": "output_dir",
            "label": "Output Folder",
            "type": "remote_folder",
            "required": False,
            "description": "Optional. Defaults to the source folder's parent.",
        },
    ],
}

import os

from client.runtime.sdk import context

try:
    from mutagen.flac import FLAC
except ImportError as exc:
    raise RuntimeError(
        "Missing dependency 'mutagen'. Install it in the target Client Python environment: "
        "python -m pip install mutagen"
    ) from exc


years = {}
sources = {}
INVALID_FILENAME_CHARS = set('\\/:*?"<>|')
SOURCE_TAG = "45b1d925-1448-5784-b4da-b89901050a13"


def get_spec(audio):
    sample_rate = audio.info.sample_rate / 1000
    if sample_rate.is_integer():
        sample_rate = int(sample_rate)
    return f"{audio.info.bits_per_sample}-{sample_rate}"


def get_source(audio, key):
    if key not in sources:
        try:
            if audio.tags.get(SOURCE_TAG, [""])[0] == "10006001":
                source = "mora"
            elif audio.tags.get("comment", [""])[0].startswith("Brought to you by OTOTOY.JP"):
                source = "OTOTOY"
            elif audio.tags.get("description", [""])[0].startswith("Interprètes"):
                source = "qobuz"
            else:
                raise ValueError("Unknown audio source")
        except Exception:
            source = context.ask(
                f"Enter the source for {key}:",
                title="Music Source",
            ) or "Unknown Source"
        sources[key] = source
    return sources[key]


def get_year(audio, key, source):
    if key not in years:
        try:
            if source == "mora":
                raise ValueError("mora year requires manual input")
            if source == "qobuz":
                year = audio.get("date")[0]
            elif source == "OTOTOY":
                year = audio.get("year")[0]
            else:
                raise ValueError("Unknown source year")
        except Exception:
            year = context.ask(
                f"Enter the year for {key}:",
                title="Release Year",
                placeholder="YYYY",
            ) or "Unknown Year"
        years[key] = year
    return years[key]


def secure_filename(filename):
    return "".join("_" if char in INVALID_FILENAME_CHARS else char for char in filename)


def find_flac_files(directory):
    paths = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        paths.extend(
            os.path.join(root, name)
            for name in files
            if not name.startswith(".") and name.lower().endswith(".flac")
        )
    return paths


def main(params):
    source_dir = str(params.get("source_dir") or "").strip()
    if not source_dir:
        raise ValueError("Source Folder is required")
    source_dir = os.path.abspath(os.path.expanduser(source_dir))
    if not os.path.isdir(source_dir):
        raise NotADirectoryError(f"Source folder does not exist: {source_dir}")

    output_dir = str(params.get("output_dir") or "").strip()
    output_dir = (
        os.path.abspath(os.path.expanduser(output_dir))
        if output_dir
        else os.path.dirname(os.path.normpath(source_dir))
    )
    output_dir = output_dir or os.path.abspath(os.sep)

    flac_files = find_flac_files(source_dir)
    os.makedirs(output_dir, exist_ok=True)
    context.progress(f"Found {len(flac_files)} FLAC files.")

    moved = skipped = 0
    for index, path in enumerate(flac_files, 1):
        audio = FLAC(path)
        artist = audio.get("albumartist", ["Unknown Artist"])[0]
        album = audio.get("album", ["Unknown Album"])[0]
        key = secure_filename(f"{artist} - {album}")
        source = get_source(audio, key)
        year = get_year(audio, key, source)
        info = secure_filename(f" ({year}) [{source}] [FLAC {get_spec(audio)}]")
        album_dir = os.path.join(output_dir, f"{key}{info}")
        os.makedirs(album_dir, exist_ok=True)

        destination = os.path.join(album_dir, os.path.basename(path))
        if os.path.exists(destination):
            skipped += 1
        else:
            os.rename(path, destination)
            moved += 1

        if index % 25 == 0 or index == len(flac_files):
            context.progress(f"Organized {index}/{len(flac_files)} FLAC files.")

    print(f"SRC: {source_dir}")
    print(f"DST: {output_dir}")
    print(f"FLAC: {len(flac_files)} | moved: {moved} | skipped: {skipped}")


if __name__ == "__main__":
    main(kwargs)
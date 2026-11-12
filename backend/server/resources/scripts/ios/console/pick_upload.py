SCRIPT_METADATA = {
    "name": "ios/console/pick_upload",
    "display_name": "Pick & Upload",
    "description": "Choose a photo or document and upload it from your iOS device.",
    "platforms": ["ios"],
    "category": "Console",
    "params": [
        {
            "name": "kind",
            "label": "Source",
            "type": "select",
            "control": "button_group",
            "options": ["photo", "file"],
            "required": False,
            "default": "photo",
            "description": "Choose a photo or document using the iOS picker."
        }
    ]
}

import os
import tempfile
from datetime import datetime
from client.runtime.sdk import artifact
from core.utils.artifact_naming import build_artifact_filename


def main():
    kind = str(kwargs.get('kind', 'photo') or 'photo').strip().lower()
    if kind == 'file':
        import dialogs
        file_path = dialogs.pick_document()
        if not file_path:
            print('No file selected')
            return
        uploaded = artifact.save(file_path, type='saved')
        print(uploaded)
        return

    if kind != 'photo':
        raise ValueError("Source must be 'photo' or 'file'")

    import photos
    image = photos.pick_image()
    if image is None:
        print('No photo selected')
        return

    # Keep the simple PIL-based JPEG upload path.
    if image.mode not in ('RGB', 'L'):
        image = image.convert('RGB')

    # The photo picker supplies a PIL image. Preserve the JPEG upload format.
    if image.mode not in ('RGB', 'L'):
        image = image.convert('RGB')
    with tempfile.TemporaryDirectory(prefix='rch-photo-upload-') as directory:
        filename = build_artifact_filename('photo', 'jpg')
        file_path = os.path.join(directory, filename)
        image.save(file_path, format='JPEG', quality=90)
        print(artifact.save(file_path, type='saved', category='downloads'))


main()
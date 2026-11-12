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
            "options": ["photo", "file"],
            "required": False,
            "default": "photo",
            "description": "Choose a photo or document using the iOS picker."
        },
        {
            "name": "file_path",
            "label": "Remote File",
            "type": "remote_file",
            "required": False,
            "default": "",
            "description": "Choose an existing file on this device, or leave blank for the iOS picker."
        }
    ]
}

import os
import tempfile
from datetime import datetime
from client.runtime.sdk import artifact


def main():
    kind = str(kwargs.get('kind', 'photo') or 'photo').strip().lower()
    selected_path = str(kwargs.get('file_path', '') or '').strip()

    # A remote selected path bypasses the iOS picker and uploads as-is.
    if selected_path:
        uploaded = artifact.save(selected_path, type='saved', category='downloads')
        print(uploaded)
        return

    if kind == 'file':
        import dialogs
        file_path = dialogs.pick_document()
        if not file_path:
            print('No file selected')
            return
        uploaded = artifact.save(file_path, type='saved', category='downloads')
        print(uploaded)
        return

    if kind != 'photo':
        raise ValueError("Source must be 'photo' or 'file'")

    import photos
    image = photos.pick_image()
    if image is None:
        print('No photo selected')
        return

    # The photo picker supplies a PIL image. Preserve the JPEG upload format.
    if image.mode not in ('RGB', 'L'):
        image = image.convert('RGB')
    filename = 'photo_{}.jpg'.format(datetime.now().strftime('%Y%m%d-%H%M%S'))
    with tempfile.NamedTemporaryFile(prefix=filename[:-4] + '_', suffix='.jpg', delete=False) as tmp:
        file_path = tmp.name
    try:
        image.save(file_path, format='JPEG', quality=90)
        uploaded = artifact.save(file_path, type='saved', category='downloads')
        print(uploaded)
    finally:
        if os.path.isfile(file_path):
            os.remove(file_path)


main()

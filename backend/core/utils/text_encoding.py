"""Strict, deterministic decoding for editable text previews (standard library only)."""

_BOMS = (
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
)


def decode_text_bytes(raw: bytes) -> tuple[str, str]:
    """Return lossless text and its write-back codec, or reject unknown/binary data."""
    for bom, codec in _BOMS:
        if raw.startswith(bom):
            encoding = "utf-8" if codec == "utf-8-sig" else codec
            text = raw[len(bom):].decode(encoding, errors="strict")
            break
    else:
        codec = "utf-8"
        text = raw.decode("utf-8", errors="strict")

    # Plain UTF-8 decoding otherwise accepts NUL-filled binary and BOM-less UTF-16.
    if any(ord(ch) < 32 and ch not in "\t\n\r\f" for ch in text):
        raise ValueError("Binary content is not editable as text")
    return text, codec


def preview_text_bytes(raw: bytes) -> dict:
    """Unknown text is display-only; replacement characters are never editable."""
    try:
        text, codec = decode_text_bytes(raw)
        return {"content": text, "encoding": codec, "editable": True}
    except (UnicodeError, ValueError):
        return {"content": raw.decode("utf-8", errors="replace"),
                "encoding": "unknown", "editable": False}


def preview_text_file(file_obj, max_preview_bytes: int) -> dict:
    """Validate the entire file, displaying at most max_preview_bytes of complete text.

    A byte-limited preview may end halfway through a UTF-8/UTF-16 character;
    incremental decoding avoids treating that incomplete display boundary as a
    broken file. Validation continues to EOF so the codec describes the file,
    not just its visible prefix. Memory stays bounded by the preview limit.
    """
    import codecs

    head = file_obj.read(max_preview_bytes)
    extra = file_obj.read(1)
    truncated = bool(extra)

    bom, codec = b"", "utf-8"
    for candidate_bom, candidate_codec in _BOMS:
        if head.startswith(candidate_bom):
            bom, codec = candidate_bom, candidate_codec
            break
    encoding = "utf-8" if codec == "utf-8-sig" else codec
    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")

    def check_binary(text):
        if any(ord(ch) < 32 and ch not in "\t\n\r\f" for ch in text):
            raise ValueError("Binary content is not editable as text")

    try:
        visible = decoder.decode(head[len(bom):], final=False)
        check_binary(visible)
        if extra:
            check_binary(decoder.decode(extra, final=False))
        while extra:
            chunk = file_obj.read(65536)
            if not chunk:
                break
            check_binary(decoder.decode(chunk, final=False))
        ending = decoder.decode(b"", final=True)
        check_binary(ending)
        if not truncated:
            visible += ending
        return {"content": visible, "encoding": codec,
                "editable": not truncated, "truncated": truncated}
    except (UnicodeError, ValueError):
        return {"content": head.decode("utf-8", errors="replace"),
                "encoding": "unknown", "editable": False,
                "truncated": truncated}


def encode_for_existing_file(content: str, codec: str, existing_bytes: bytes) -> bytes:
    """Verify original bytes and fully encode before caller opens the file for writing."""
    if not isinstance(content, str):
        raise ValueError("content must be text")
    try:
        _, actual_codec = decode_text_bytes(existing_bytes)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("File encoding is unknown; editing is disabled") from exc
    if codec != actual_codec:
        raise ValueError("File encoding changed or does not match the preview")

    if codec == "utf-8-sig":
        output = b"\xef\xbb\xbf" + content.encode("utf-8", errors="strict")
    elif codec == "utf-16-le":
        output = b"\xff\xfe" + content.encode("utf-16-le", errors="strict")
    elif codec == "utf-16-be":
        output = b"\xfe\xff" + content.encode("utf-16-be", errors="strict")
    elif codec == "utf-8":
        output = content.encode("utf-8", errors="strict")
    else:
        raise ValueError("Unsupported text encoding")
    # Saving must not produce bytes that the preview would subsequently mark read-only.
    decode_text_bytes(output)
    return output

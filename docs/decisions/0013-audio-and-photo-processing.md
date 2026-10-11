# 0013. Audio: ffmpeg, then afconvert, else keep the original; photos without EXIF

- Status: accepted
- Date: 2026-10-10

## Context

Voice notes are kept forever (rule 3), so their size matters: 32 kbps mono AAC is about 1.5 MB
for six minutes and plays in Obsidian and in Drive. The Docker image has ffmpeg; a Mac running the
API directly may only have Apple's `afconvert`. Transcription quality is best on the original
audio. iPhone photos are large HEIC files with GPS and device data.

## Decision

* Compress with `ffmpeg -ac 1 -c:a aac -b:a <N>k -movflags +faststart`, falling back to
  `afconvert -f m4af -d aac -c 1 -b <N*1000>`. If neither is installed or both fail, keep the
  original bytes with their own extension, log a warning and record it; never fail a capture
  because of compression. Keep an `.m4a` original that is already smaller than the output.
* Transcribe the original upload unless it is over 24 MB or a format hosted APIs reject; then
  transcribe the compressed copy.
* Photos: open with Pillow + pillow-heif, apply the EXIF orientation, fit within
  `photo_max_dimension`, save as progressive JPEG at `photo_jpeg_quality`, and drop all EXIF.

## Consequences

* An uncompressed fallback file (e.g. `.wav`) is listed in `audio` and embedded in the day file,
  but `classify_path` only calls `.m4a` files "audio", so the indexer treats it as "other".
* Photo copies carry no capture time or GPS; the day file and the originals in the photo library
  have those.
* `afconvert` cannot encode AAC inside some sandboxes (the codec is hidden); the real-encoder test
  skips there.

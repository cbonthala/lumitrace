# 0065. Photo-only captures stay in the day file and are sent to fill/update

- Status: accepted
- Date: 2026-10-19

## Context

A Flash Send with a photo and no recording is a note capture: the JPEG is stored in the day
folder as `photo-NN.jpg`, and the Frame should list it in front matter and as an Obsidian
wiki embed `![[photo-NN.jpg]]` in that capture's transcript block. There is no public URL;
the embed is the reference.

Two gaps showed up on a closed-day photo Send:

1. Generate re-reads the live day after the model returns so an Obsidian edit during the call
   is kept. In that same window Drive can also serve (or Obsidian can save) an older copy that
   omits the capture just merged. Apply then wrote that older copy, leaving the JPEG on disk
   with `photos: []` and no embed.
2. `format_captures` skipped any capture with no transcript text, so fill/update never saw
   the filename and could not put it in Day context → Media.

## Decision

* After the model returns, merge every capture from the in-memory day into the freshly read
  file before applying generated content. `merge_capture` is a no-op for ids already present,
  so owner transcript edits stay; missing ids (and their photos in front matter) come back.
* `format_captures` includes a capture that has photos or audio even when the text is empty,
  and lists those filenames as capture metadata.

## Consequences

* A photo-only Send on a closed day still runs generate (the new capture id changes the
  source hash). The JPEG, front matter list, and wiki embed survive that write.
* The model may list the filename under Media; it must not invent a description of the
  picture (existing fill/update evidence rules).
* Not yet verified against a live Obsidian client saving during generate.

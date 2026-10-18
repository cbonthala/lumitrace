# 0054. Flash reviews a recording before sending

- Status: accepted
- Date: 2026-10-17

## Context

The Flash web app sent a recording the moment the red button was tapped a second time. The
owner wants to pause, listen back, crop, and only then choose Send or Discard. The recording
API still accepts one audio file and has no trim parameters. A photo with no recording should
still be savable from the same card.

## Decision

* Four states on the Capture card: idle, recording, paused, review. The red button starts, or
  stops into review. It does not upload.
* **Pause / Resume** call `MediaRecorder.pause` and `resume` on the same recorder, so the take
  stays one file. The timer skips paused time. The screen wake lock stays on while paused. If
  the browser has no pause, the button is hidden and stop still opens the review. Pause,
  resume, play, and discard are icon buttons (two bars, triangle, trash).
* **Review** plays the take and shows two handles on a waveform. Send uploads through the
  existing outbox. Discard drops the take. Photos, place, and the filing day stay attached
  until Send or Discard.
* **Send** sits in the bottom corner of the card. With a recording in review, it sends that
  recording (`POST /recordings`). With no recording and at least one photo, it sends those
  photos as a note (`POST /notes`). It stays disabled until there is something to send.
* An uncropped take (handles still at the ends) is the original blob. A crop is decoded in the
  browser, sliced, and re-encoded by playing that slice into a new `MediaRecorder`. That second
  encode runs about as long as the part you keep. If the browser cannot decode the file, crop
  is hidden and Send uploads the whole take.

## Consequences

* `POST /recordings` is unchanged. A photo with no audio uses the existing notes endpoint.
  Shortcuts are unchanged.
* A cropped file is a second encode, so it is not bit-for-bit the microphone audio. The
  original is what gets sent when you do not move the handles.
* Not yet checked on a real iPhone: pause, playback of the just-recorded `.m4a`, and a crop
  longer than a few minutes.

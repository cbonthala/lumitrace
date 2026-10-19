# 0063. Flash requires an explicit filing date before Send

- Status: accepted
- Date: 2026-10-19

## Context

The web app's **Filing under** chip started on today and treated picking today as "no date".
Send then left `date` empty, so the Prism used the capture time's day. A recording meant for
yesterday was easy to file under today. The owner asked to choose the day, including today,
before Send, and to see a popup if they skip it.

## Decision

* The chip starts unselected (`pick a day`). Choosing today stores today's `YYYY-MM-DD`; it is
  no longer cleared.
* Send, photo-only Send, and **Upload audio** call `requireFilingDate`. If no day is chosen, a
  sheet titled **Select the date** offers Today, Yesterday, or another day. **Send for this day**
  continues the upload; Cancel does not.
* The API still accepts an empty `date` (ADR 0017). iPhone Shortcuts are unchanged.

## Consequences

* A reload clears the choice, so each session asks again. The chosen day is kept for later
  captures in the same session.
* Not yet checked on a real iPhone Home Screen.

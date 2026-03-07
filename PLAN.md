# Add Configurable Preparation-Week Rules For Delivery Scheduling

## Summary
Replace the fixed earliest-week matrix with a true preparation-time model driven by dashboard settings. The system will compute the earliest possible delivery week as `current ISO week + applicable prep weeks`, then choose the first valid tour week on or after that candidate. Rules will be global, repeat every year, allow multiple non-overlapping week ranges, and use a default baseline of `2` prep weeks outside custom ranges.

## Implementation Changes
- Add a new persistent settings table for delivery preparation rules:
  - global scope only for v1
  - fields: `id`, `week_from`, `week_to`, `prep_weeks`, `is_default`, timestamps
  - enforce one default rule and non-overlapping custom ranges
  - rules repeat every year and use ISO week numbers `1-52`
- Add backend API endpoints in [`app.py`](C:/Users/Lili/Documents/GitHub/STD/app.py) for admin-only management:
  - `GET /api/settings/delivery-preparation`
  - `PUT /api/settings/delivery-preparation`
  - response shape includes the default prep weeks plus the ordered list of custom ranges
  - validate ranges server-side: `week_from <= week_to`, `prep_weeks >= 0`, no overlaps, no duplicate default
- Add a small data-access layer for these settings using the existing DB helpers in [`db.py`](C:/Users/Lili/Documents/GitHub/STD/db.py).
- Update [`delivery_logic.py`](C:/Users/Lili/Documents/GitHub/STD/delivery_logic.py):
  - keep `TOUR_TO_SCHEDULE_CODE` and `VALID_WEEKS_BY_CODE`
  - remove `EARLIEST_WEEK_BY_TOUR` as the runtime source of truth
  - add rule lookup for the current ISO week:
    - if current week falls inside a configured custom range, use that `prep_weeks`
    - otherwise use the default `2` weeks
  - compute earliest candidate week by real calendar math, including correct next-year rollover
  - select the first valid tour week on or after that candidate, rolling into the next year when needed
  - preserve current requested-week logic after earliest-week determination, except that year rollover should now be calendar-correct
  - preserve current public API and debug logging keys
- Add a real settings UI in [`front-end/my-react-app/src/pages/SettingsPage.jsx`](C:/Users/Lili/Documents/GitHub/STD/front-end/my-react-app/src/pages/SettingsPage.jsx):
  - admin-only editor
  - one default prep-weeks input
  - editable list of custom ranges with `week_from`, `week_to`, `prep_weeks`
  - add/remove rows
  - client-side validation for obvious overlap/input errors
  - save via `PUT /api/settings/delivery-preparation`
  - read-only or hidden state for non-admin users

## Behavior Rules
- Earliest possible delivery is no longer taken from a hardcoded week-by-tour table.
- New algorithm:
  - determine today’s ISO year/week
  - resolve the applicable prep-weeks rule for that week
  - add prep weeks to the current ISO week using real calendar rollover
  - for the resolved tour rhythm, find the first valid service week on or after the candidate week
  - if that valid week lands in the next ISO year, return the next year in `delivery_week`
- Example:
  - default prep = `2`
  - custom range `7-17 => 4`
  - today = week `8`
  - candidate = week `12`
  - `D2` (`2.3` rhythm) returns week `14`
- Requested-week behavior remains layered on top of the earliest possible week; this change only replaces how earliest possible week is computed.

## Test Plan
- Add backend tests for rule validation:
  - default rule required
  - invalid week bounds rejected
  - overlapping ranges rejected
  - adjacent ranges accepted
- Add delivery-logic tests for:
  - default prep weeks outside custom ranges
  - custom prep weeks inside configured ranges
  - tour-specific next valid week selection for all six tours
  - year rollover from late weeks into next ISO year
  - requested-week calculations still respecting the new earliest possible week
  - Braun vs non-Braun requested-week offsets unchanged
- Add API tests for:
  - admin can read/write settings
  - non-admin cannot modify settings
  - malformed payloads return `400`
- Add UI tests or at minimum manual verification scenarios:
  - load current settings
  - add/edit/delete non-overlapping ranges
  - block overlap before save
  - save and reload persists correctly

## Assumptions
- V1 is global only; no per-branch overrides.
- Rules repeat every year by ISO week number.
- Outside custom ranges, the baseline is always `2` prep weeks.
- Year-end behavior should become calendar-correct rather than preserving the current same-year wrap quirk.
- Existing callers of `delivery_logic.calculate_delivery_week()` and `is_tour_valid()` remain unchanged.

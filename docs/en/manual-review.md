# Manual Review

[English](README.md) · [Français](../fr/manual-review.md)

← [Documentation](README.md)

Sidebar **Manual Review** block: the batch scrapes providers as usual but **does not write to Kavita**. Each series is parked as `PENDING_REVIEW` with scored candidates (above/below the reliability threshold).

![Scraping options — Manual Review](../../assets/docs-manual-review.png)

**Super Manual Review** expands every usable scraper (not only the three cascade slots). After provider #1 seeds ISBN/authors, the others run in parallel — still one series at a time, and each scraper's timer still applies. **Cover picker** lets you choose a cover before confirm. **Review sounds** play short UI tones. **Purge queue** clears parked series.

Open the review modal from the topbar badge. **Search** re-queries under another title; **View in Kavita** opens the series. Cards sit **Above threshold** (or **Show below threshold**); tick **Source** to fuse empty fields onto the teal **Master**. **Manual completion** (in the modal) shows a box on each field: Master starts fully checked; ticking a field on another card takes that field from Master — so you can keep MangaBaka's publisher and take AniList's cover. **Merge fields** (only with Manual completion on) lets list fields — tags, genres, staff — be ticked on several cards; values are concatenated, without extra dedup. Scalars stay one-winner. Source boxes are hidden while this is on; the Master badge stays. Clean the result in **Adjust before send** before it goes to Kavita. **List** jumps to another parked series. Footer: **Purge queue**, **Skip**, **Pick** — keys `1`–`9`, arrows, `Enter`, `Esc`.

![Manual review modal](../../assets/docs-manual-review-modal.png)

If **Cover picker** is on, the next step is this grid: **Current selection**, live search across all providers, click a thumbnail to change it. Kavita is only written on confirm. Footer: **Back**, **Keep provider cover**, **Continue** (`Enter` / `Esc` / `Backspace`).

![Manual review — cover picker](../../assets/docs-manual-review-cover.png)

If **Edit before confirm** is on (`MANUAL_REVIEW_EDIT`), **Adjust before send** is the last recap on the dashboard: cover URL, title, localized title, year, status, age rating, format, publisher, summary, genres, tags, staff — with the Master / Fusion bar. Each writable field has a tick: on means it is written, off leaves Kavita as-is. Title and format are display-only. A series **Targeted fields** override that dropped a field locks that tick. Footer: **Back**, **Skip**, **Confirm** (`Enter` / `Esc` / `Backspace`). *(Note: In the [Workshop](volumes.md), this intermediate screen is omitted; picks and manual field completion stage directly onto the workshop series card, which acts as the editing sheet).*

![Manual review — adjust before send](../../assets/docs-manual-review-edit.png)

Session recap and achievements land on `/stats`.

Turning the mode off clears any stranded queue so series are not left frozen out of auto-sync.

Hiding Manual Review in [Light mode](dashboard.md#light-mode) also switches the mode off and empties the queue.

Related settings: `MANUAL_REVIEW_MODE`, `MANUAL_REVIEW_EDIT`, `MANUAL_REVIEW_SUPER`, `MANUAL_REVIEW_SOUNDS` — see [Configuration](configuration.md). The Auto [per-field map](dashboard.md) does not apply here.

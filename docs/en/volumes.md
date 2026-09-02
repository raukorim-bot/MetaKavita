# Per-volume / album metadata

[English](README.md) · [Français](../fr/volumes.md)

← [Documentation](README.md)

Off by default (`VOLUME_ENRICHMENT_ENABLED`). While it is off, the buttons are hidden and the API answers 403. Enable it from the sidebar **Volumes & albums** block (marked experimental).

![Scraping options — Volumes & albums](../../assets/docs-volumes-sidebar.png)

Where the [Inventory](inventory.md) tells you what is missing, this fills in what is there.

Three surfaces, kept apart:

* **📑 Volume report** (on the series row) — inventory only: owned vs expected, missing ISBN, forced expected, exclusion. Footer: **Refresh**, **Workshop** link, CSV / TXT.
* **Toolbar VOLUMES** — **Workshop** opens `/volumes` (rail / last series, no dashboard pick). Automatic pass on the ticked series, cancellable. Honours magic links already stored in the workshop. No Magic Input in the toolbar.
* **Workshop** `GET /volumes` or `GET /series/<id>/volumes` — a standalone page (like `/stats`). On open: Kavita + Meta, **no scrape**. Series card (teal) ≠ volume cards (orange). **Empty** fields are amber, but they **keep the same order**. Short fields (year, status, age, staff) sit three to a row. Extra staff sit behind **More fields (x filled / y)** (the fold is remembered, with a real-time completion counter). **Magic Input** is a labelled row, visible at a glance (pressing Enter triggers the search directly). The series title opens the Kavita sheet. The volume bar stays on screen (selected count, send). `/` focuses the rail search; ← → grey out at the ends of the list. The top navigation bar includes a permanent **Buy me a coffee** button (☕) with instant feedback and supporter cooldown. The supporter nagware overlay can also appear rarely after successful writes to Kavita (`workshop_craft` variant, under strict safeguards: 7-day honeymoon, at least 10 items processed activity threshold, max 1–2 times per day, 30-day honor snooze). The live log sits on the right. Covers sit as a 2:3 book with a **Pick** overlay; the chosen URL is written on Send, not through `/update-cover`. Edit in place with automatic real-time draft persistence (survives an F5 reload). Manual Review / Super Review (series or volume) allow adjusting metadata (single candidate with pre-selection and cover thumbnails, source fusion, or per-field manual completion, honouring any typed ISBN) going through the proper review steps (pick, cover, preview/edit) before staging the sheet upon confirmation; they do **not** write Kavita. **Send** one volume / the sheet / the selection / every volume is what writes. Send **overwrites** fields already filled, including locked ones (an empty value, including localized name, is never written). Reset = Meta + reload Kavita, **not** a rewind of writes already in Kavita. Reset on one volume also reopens that unit for the automatic pass. The rail reuses the dashboard search, library, status and hide-ignored filters. A click loads that series beside the list, without a page reload. Covers already in Kavita are kept on disk.

![Volume report](../../assets/docs-volume-report.png)

Written: **album title, summary, release date, ISBN and cover**, and only into empty fields unless Force. A field you filled by hand, or locked in Kavita, is left alone.

A pass over the series you tick sits next to Analyze, with the same progress bar and Cancel — the same selection the scraping batch uses.

Sources: ComicVine (a hundred issues per request, `fetch_volume` for a single issue), Bédéthèque and Planète BD (targeted crawl: only owned volumes are opened, `should_cancel` in the loop), Manga-News for French manga volumes (Kavita alternative titles first), Metron (paginated issue list), and, for volumes that already carry an ISBN, Google Books then Open Library then Hardcover then openBD if installed. Manga-Sanctuary, once it declares `fetch_volume_index`, sits just behind Manga-News. Author credits are a separate switch (`VOLUME_ENRICH_CREDITS`), off by default (one extra request per album).

`VOLUME_FORCE_OVERWRITE` lifts the fill-the-blanks rule for a run, for instance after switching provider.

## One-shots

A one-shot is a single file; Kavita gives it no volume number. When it carries an **ISBN**, MetaKavita goes straight to the ISBN providers. When it has neither volume number nor ISBN, the automatic pass sets it aside — unless the workshop already stored a Magic Input. Owning only volume 1 of a numbered series is still enriched.

## Manga

Manga-News lists French volumes (album title, summary, ISBN, release date), one page per **owned** volume — first on a manga library, last resort on Comic (Flexible). An HTML index that hits its cap no longer stops the cascade: MangaDex is still asked for missing covers. Stop during a covering text index keeps that index and does not then fetch MangaDex. Volumes that already carry an ISBN are looked up on Google Books, then Open Library, Hardcover, openBD.

`VOLUME_ENRICH_EXPERIMENTAL` searches Google Books by series title plus volume number when there is no ISBN and no Manga-News hit. Each candidate's title must contain the series name *and* announce the volume number before anything is written. Read the preview before applying.

Hiding volume enrichment in [Light mode](dashboard.md#light-mode) also switches the pass off.

See [Configuration](configuration.md) for `VOLUME_PROVIDER`, `VOLUME_NO_MANGA_FALLBACK`, and related keys.

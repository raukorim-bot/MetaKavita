# Per-volume / album metadata

[English](README.md) · [Français](../fr/volumes.md)

← [Documentation](README.md)

Off by default (`VOLUME_ENRICHMENT_ENABLED`). While it is off, the buttons are hidden and the API answers 403. Enable it from the sidebar **Volumes & albums** block (marked experimental).

![Scraping options — Volumes & albums](../../assets/docs-volumes-sidebar.png)

Where the [Inventory](inventory.md) tells you what is missing, this fills in what is there.

Three surfaces, kept apart:

* **📑 Volume report** (on the series row) — inventory only: owned vs expected, missing ISBN, forced expected, exclusion. Footer: **Refresh**, **Workshop** link, CSV / TXT.
* **Workshop Access on Dashboard** — **Workshop** sits prominently in the sticky topbar (`header.topbar`) as well as in the series toolbar header, featuring its dedicated SVG craft icon and teal theme, opening `/volumes` at any time (the rail or last-visited series loads the sheet without requiring a prior dashboard selection). Automatic pass available on ticked series, cancellable. Honours magic links already stored in the workshop. No Magic Input in the toolbar.
* **Workshop** `GET /volumes` or `GET /series/<id>/volumes` — a standalone page (like `/stats`). On open: Kavita + Meta, **no scrape**. Modern, compact, high-density interface (series card height halved, volume cards slimmed by more than half, displaying 2 to 3 volume cards simultaneously without endless scrolling). Modernized form fields inspired by the sleek Manual Review and “Adjust before send” screens (modern dark slate `#141926` background, 8px rounded corners, generous padding, natural sentence-case labels, eliminating loud yellow borders in favor of a soft subtle tint). Series card (teal) ≠ volume cards (orange). **Series-to-volumes duplication**: every compatible series field features a 1-click `To volumes` micro-button cascading its value (writers, pencillers, staff, genres, tags, age rating, summary, language, links) across all loaded volume cards, automatically marking them dirty and scheduling SQLite draft persistence. A global **Duplicate to volumes** button in the series card actions cascades all filled common metadata at once. Volume cards gain modern status chips (`DONE`, `STAGED`, `PENDING`). Short fields (year, status, age, staff) sit three to a row. Extra staff sit behind **More fields (x filled / y)** (the fold is remembered, with a real-time completion counter). **Magic Input** is a compact labelled bar, visible at a glance (pressing Enter triggers the search directly). The series title opens the Kavita sheet. The sticky volume action bar floats cleanly in dark glassmorphism (selected count, grouped buttons, gradient orange primary send). `/` focuses the rail search; ← → grey out at the ends of the list; rail items are compacted to 48 px (+15% vertical capacity). The top navigation bar includes a permanent **Buy me a coffee** button (☕) with instant feedback and supporter cooldown. The supporter nagware overlay can also appear rarely after successful writes to Kavita (`workshop_craft` variant, under strict safeguards: 7-day honeymoon, at least 10 items processed activity threshold, max 1–2 times per day, 30-day honor snooze). The live log sits on the right. Covers sit as a prominent 2:3 book (136×204 px series, 104×156 px volumes) with a **Pick** overlay button; series and volume covers integrate seamlessly beside headers and top fields while lower metadata (summary, more fields, actions) flows full-width beneath them to eliminate any dead space. The chosen URL is written on Send, not through `/update-cover`. Edit in place with automatic real-time draft persistence for both series and volume cards (debounced 500 ms, external IDs and changes preserved in SQLite `_staged: True`, safe from background pass overwrites, survives an F5 reload and rail navigation). Manual Review / Super Review (series or volume) allow adjusting metadata (multi-provider candidate gathering querying all active scrapers for ISBN and title with pre-selection, dedicated volume keyboard navigation with Escape/Enter/Arrows/digits 1–9/double-click and cover thumbnails, retaining source provider, source fusion, or per-field manual completion, honouring any typed ISBN) going through the proper review steps (pick, cover, preview/edit) before staging the sheet upon confirmation; they do **not** write Kavita. **Send** one volume / the sheet / the selection / every volume is what writes, automatically purging staged covers on success to prevent cover resurrection upon reload, and invalidating hygiene caches. Every successful write emits a real-time confirmation line in the live log console (with series pill, green ✅ status, volume number, and written fields summary). Send **overwrites** fields already filled, including locked ones (an empty value, including localized name, is never written). Reset = Meta + reload Kavita, **not** a rewind of writes already in Kavita. Reset on one volume also unblocks that series for automatic library pass resumption. The rail reuses the dashboard search, library, status and hide-ignored filters. A click loads that series beside the list, without a page reload. Covers already in Kavita are kept on disk.

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

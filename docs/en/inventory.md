# Library Inventory

[English](README.md) · [Français](../fr/inventory.md)

← [Documentation](README.md)

On by default (`LIBRARY_INVENTORY_ENABLED`). Read-only: it never writes volume metadata and never merges series. Untick **Library inventory** in the sidebar to hide the panel; scraping and series metadata are untouched.

![Scraping options — Inventory](../../assets/docs-inventory-sidebar.png)

An **Inventory** panel above the series list tells you which series are incomplete. **Analyze library** / **Quick analyze** run in the background: they count the volumes (or chapters) you own in Kavita, ask the provider cascade how many there should be, and cluster look-alike series. **Missing details** and **Duplicate details** (or the **Duplicates** chip) open the lists.

![Inventory panel — health bar, Missing / Duplicates / No id](../../assets/docs-toolbar-inventory.png)

You get:

* a health bar
* **Missing / Duplicates / No id** chips
* an `N/M` badge on each row, coloured by completion
* a per-series report with missing numbers folded into ranges
* CSV / TXT exports
* duplicate groups you can dismiss

**Missing details** (or the **Missing** chip) lists series whose owned count is below the catalogue expected (1…N): **Series**, **State** (`N/M`, Δ missing), **Publication**, **Missing** (ranges, or `ch.` for chapters). **Include series with unknown expected (N/?)** adds the unknowns. **Volume report** opens the [per-series report](volumes.md). CSV / TXT at the bottom.

![Missing details](../../assets/docs-missing-details.png)

**Duplicate details** opens this modal. **Threshold** (Soft 0.85 / Medium 0.92 / Strict 0.97) needs a new Analyze. Each group shows score and reason (`same_external_id`, close title, …); **Open Kavita**, **Not a duplicate**, **Ignore**. Tick **Trash** on the extra copies (at least one series per group stays unticked). **Unknown path** means run Analyze again.

**Folder path prefix** (`INVENTORY_FOLDER_PATH_PREFIX`) is glued in front of each Kavita path in the script — e.g. `/mnt/media` + `/comics/…` → `/mnt/media/comics/…`. **Duplicate trash folder** (`INVENTORY_FOLDER_TRASH`) must sit outside Kavita libraries. Then **Copy script** or **Download .sh** (`Trash (mv)` or `Delete (rm -rf)`), plus CSV / TXT.

![Duplicates modal](../../assets/docs-duplicates-modal.png)

MetaKavita never runs that script and never deletes Kavita records: a delete that leaves the files on disk comes back on the next scan.

Expected counts can be forced by hand (**Forced expected** in the [volume report](volumes.md)). A series no catalogue will ever know can be excluded from the counters (**Exclude from inventory**) while still being scraped.

Switch it off from the sidebar (**Inventory** category) and the panel, badges and API all go away. Hiding Inventory in [Light mode](dashboard.md#light-mode) also switches it off.

See [Volumes](volumes.md) for writing per-album metadata.

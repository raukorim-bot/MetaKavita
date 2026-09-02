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

**Missing details** (or the **Missing** chip) lists series whose owned count is below the catalogue expected (1…N): **Series**, **State** (`N/M`, Δ missing), **Publication**, **Missing** (ranges, or `ch.` for chapters), and a **Quick Exclude** button to immediately dismiss a series from inventory counting without opening Options. **Include series with unknown expected (N/?)** adds the unknowns. **Volume report** opens the [per-series report](volumes.md). CSV / TXT at the bottom.

![Missing details](../../assets/docs-missing-details.png)

**Duplicate details** opens this modal. **Threshold** (Soft 0.85 / Medium 0.92 / Strict 0.97) needs a new Analyze. Each group shows score, detection reasons, and real volume and chapter counts for each copy (`X tomes · Y ch.`), highlighted with a "🌟 Recommended (most complete)" badge for the richest edition.
* Actions on copies: **Open Kavita**, **Not a duplicate**, **Ignore**, and **Mark as resolved** (dismisses handled groups without altering false-positive stats; dismissed groups are shared between individual libraries and the "All" view).
* Tick **Trash** on extra copies: at least one series per group stays unticked, and an explicit confirmation alert warns you if you accidentally select "Trash" on a copy richer than the kept one.
* **Unknown path** means run Analyze again.

**Folder path prefix** (`INVENTORY_FOLDER_PATH_PREFIX`) is glued in front of each Kavita path in the script — e.g. `/mnt/media` + `/comics/…` → `/mnt/media/comics/…` or `C:/Media` on Windows. **Duplicate trash folder** (`INVENTORY_FOLDER_TRASH`) accepts both POSIX and Windows paths (`C:/...`, `D:\...`) and must sit outside Kavita libraries. Saving folder settings only updates paths without touching global server configuration.
* **Script format**: choose between POSIX Bash (`.sh`) and Windows PowerShell (`.ps1`). Then **Copy script** or **Download (.sh / .ps1)** in `Trash (mv)` or `Delete (rm -rf)` mode, plus CSV / TXT exports.
* **⚡ Trigger Kavita Scan**: once you have run the script on your server or NAS, click this button directly in the modal to ask Kavita to rescan the library immediately, without switching to the Kavita interface.
* **Safe empty series purge**: if moving files left an empty series shell in Kavita (0 volumes), MetaKavita detects it and offers a 1-click purge (`/purge-empty`) directly in the volume report modal, safely verifying that no volumes or chapters remain before deleting the shell.

![Duplicates modal](../../assets/docs-duplicates-modal.png)

MetaKavita never runs that file-moving script itself: disk operations remain entirely under your control.

Expected counts can be forced by hand (**Forced expected** in the [volume report](volumes.md)), instantly reusing cached catalog data without redundant provider scrapes. A series no catalogue will ever know can be excluded from the counters (**Exclude from inventory**) while still being scraped.

Switch it off from the sidebar (**Inventory** category) and the panel, badges and API all go away. Hiding Inventory in [Light mode](dashboard.md#light-mode) also switches it off.

See [Volumes](volumes.md) for writing per-album metadata.

# MetaKavita Companion

[English](README.md) · [Français](../fr/companion.md)

← [Documentation](README.md)

Chrome + Firefox MV3 (extension **1.0.29**, MetaKavita **1.6.5**+; the status dot needs **1.7.3**+). **Beta / early access** — sideload only; **not** on the Chrome Web Store or Firefox AMO.

Floating icon menu on Kavita **series** pages (not the reader). The feather opens a two-ring constellation, and carries a **status dot**.

### Two modes

**Simplified** (the default on a fresh install): five buttons, in plain words — *Complete this series*, *Change the cover*, *Complete without asking me*, Config, coffee. **Expert** (kept on an install that is already paired): all seven, under their MetaKavita names — Super Review, Auto, Cover, Volume Workshop, Open in MetaKavita, Config, coffee.

The difference is not just the number of buttons. In simplified mode, **Auto asks before writing**: it replaces your metadata with whatever MetaKavita finds, without showing it to you. The confirmation offers a third way out, *See it before writing*, which switches to Super Review. In expert mode it fires on click — that is the whole point.

The mode lives in **Config → Interface**.

### The dot

| Colour | Meaning |
|---|---|
| 🟢 | handled — enriched, or searched and not found |
| 🟡 | being processed, queued, or waiting in Manual Review |
| 🔵 | known to MetaKavita, not enriched yet |
| 🔴 | ignored |
| ⚫ | never seen by MetaKavita |

On an instance older than 1.7.3 there is simply no dot.

![Companion menu on a Kavita series page](../../assets/docs-companion-fab.png)

Super Review embeds `/companion/embed` when URL schemes match. An HTTPS Kavita with an HTTP MetaKavita cannot embed it (mixed content): the review opens in a small **dedicated window** centred over Kavita and closes itself when it finishes. Cover previews that travel through MetaKavita are fetched by the extension, so they render in both cases.

Companion one-shots **override** Manual Review / Super toggles, jump ahead of a running batch queue (after the in-flight job), and **replace** any pending job for the same series.

## Install (sideload)

**Chrome / Edge:** download [`metakavita-companion-chrome.zip`](https://github.com/raukorim-bot/MetaKavita/raw/main/companion/dist/metakavita-companion-chrome.zip) → extract → `chrome://extensions` → Developer mode → Load unpacked.

**Firefox:** download [`metakavita-companion-firefox.zip`](https://github.com/raukorim-bot/MetaKavita/raw/main/companion/dist/metakavita-companion-firefox.zip) → extract → `about:debugging` → Load Temporary Add-on → `manifest.json`.

**Config** (or the extension popup) is **Companion settings**: MetaKavita URL, webhook token (from MetaKavita → [Configuration](configuration.md) / Auto-Sync), **Show the action buttons**, **Refresh cover after confirm (cache bust)**, **Interface** (Simplified / Expert), language (**Auto (browser)** / FR / EN). Then **Save**, **Test connection** — which also reports your instance's version — and **Enable on this Kavita site**.

"Enable on this Kavita site" only appears in the toolbar **popup**: opened as an options page, it would read its own tab.

![Companion settings](../../assets/docs-companion-config.png)

Full guide: [`companion/README.md`](../../companion/README.md) (also Help menu). Pack: `node companion/scripts/pack.mjs`.

Both archives are also offered by the **card under the top bar**. Its cross hides it for that browser; **Help → Download Companion** brings it back.

Webhook flags used by the extension are documented in [Automation](automation.md). Companion **Auto** follows the same Auto mapping as the dashboard when it is enabled; **Super Review** does not.

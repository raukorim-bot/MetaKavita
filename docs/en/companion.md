# MetaKavita Companion

[English](README.md) · [Français](../fr/companion.md)

← [Documentation](README.md)

Chrome + Firefox MV3 (extension **1.0.28**, MetaKavita **1.7.0**+). **Beta / early access** — sideload only; **not** on the Chrome Web Store or Firefox AMO.

Floating icon menu on Kavita **series** pages (not the reader). The feather opens the arc: **Super Review**, **Auto**, **Cover**, **Config**, **Buy me a coffee**.

![Companion menu on a Kavita series page](../../assets/docs-companion-fab.png)

Super Review embeds `/companion/embed` when URL schemes match. An HTTPS Kavita with an HTTP MetaKavita cannot embed it (mixed content): the review opens in a small **dedicated window** centred over Kavita and closes itself when it finishes. Cover previews that travel through MetaKavita are fetched by the extension, so they render in both cases.

Companion one-shots **override** Manual Review / Super toggles, jump ahead of a running batch queue (after the in-flight job), and **replace** any pending job for the same series.

## Install (sideload)

**Chrome / Edge:** download [`metakavita-companion-chrome.zip`](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-chrome.zip) → extract → `chrome://extensions` → Developer mode → Load unpacked.

**Firefox:** download [`metakavita-companion-firefox.zip`](https://github.com/raukorim-bot/MetaKavita/raw/dev/companion/dist/metakavita-companion-firefox.zip) → extract → `about:debugging` → Load Temporary Add-on → `manifest.json`.

**Config** (or the extension popup) is **Companion settings**: MetaKavita URL, webhook token (from MetaKavita → [Configuration](configuration.md) / Auto-Sync), **Show Super / Auto / Cover buttons**, **Refresh cover after confirm (cache bust)**, language (**Auto (browser)** / FR / EN). Then **Save**, **Test connection**, **Enable on this Kavita site**.

![Companion settings](../../assets/docs-companion-config.png)

Full guide: [`companion/README.md`](../../companion/README.md) (also Help menu). Pack: `node companion/scripts/pack.mjs`.

Both archives are also offered by the **card under the top bar**. Its cross hides it for that browser; **Help → Download Companion** brings it back.

Webhook flags used by the extension are documented in [Automation](automation.md). Companion **Auto** follows the same Auto mapping as the dashboard when it is enabled; **Super Review** does not.

/**
 * Bytes that go into (and are checked against) the shipped zips.
 *
 * The zips are packed by hand, usually on Windows, where git checks text files
 * out with CRLF. The CI runner checks the same files out with LF, so a
 * byte-for-byte comparison failed on whichever files happened to be packed
 * from a CRLF copy — and would keep failing until someone repacked on Linux.
 * Normalising line endings here makes the artifact identical whatever the
 * machine that built it.
 */
const TEXT_EXT = [".js", ".mjs", ".json", ".html", ".css", ".md", ".txt"];

export function isTextEntry(name) {
  const lower = String(name).toLowerCase();
  return TEXT_EXT.some((ext) => lower.endsWith(ext));
}

/** LF for text entries; images and anything else byte-for-byte. */
export function zipBytes(name, buf) {
  if (!isTextEntry(name)) return buf;
  const text = buf.toString("utf8");
  if (!text.includes("\r\n")) return buf;
  return Buffer.from(text.replace(/\r\n/g, "\n"), "utf8");
}

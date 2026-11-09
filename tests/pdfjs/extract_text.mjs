// Prints a PDF's text as pdf.js extracts it, one page after another.
//
//   node extract_text.mjs <file.pdf>
//
// Text items are joined the way pdf.js's own text layer reads them: each item's
// string as-is, with a line break wherever pdf.js marks an end of line.

import { readFile } from "node:fs/promises";
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";

const [pdfPath] = process.argv.slice(2);
if (!pdfPath) {
  console.error("usage: node extract_text.mjs <file.pdf>");
  process.exit(2);
}

const document = await getDocument({
  data: new Uint8Array(await readFile(pdfPath)),
  verbosity: 0,
}).promise;

const pageTexts = [];
for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber++) {
  const page = await document.getPage(pageNumber);
  const { items } = await page.getTextContent();
  pageTexts.push(items.map((item) => item.str + (item.hasEOL ? "\n" : "")).join(""));
}
process.stdout.write(pageTexts.join("\n"));

import { useState } from "react";
import { webUrl } from "@/panels/format";
import type { Source } from "@/types";

// The cited page's image in a source (DAR-654), so a number taken from a table can be
// checked against the table itself. The server sends `image` only for pages that were
// rendered (divrag/pages_static.py); it is null otherwise and nothing is shown. The
// image is only ever a site-relative /pages/ path: anything else in the data is ignored,
// so a payload can't point the page at another origin.

const SITE_IMAGE = /^\/pages\/[A-Za-z0-9._\-/]+\.jpg$/;

export function imageSrc(image: unknown): string | null {
  return typeof image === "string" && SITE_IMAGE.test(image) && !image.includes("..") ? image : null;
}

export function PageImage({ source: s }: { source: Source }) {
  const src = imageSrc(s.image);
  // The image is dropped once it fails to load (a page left out of a partial render, or a
  // deployment without images): a broken-image icon would say less than nothing.
  const [failed, setFailed] = useState(false);
  if (!src || failed) return null;
  const href = webUrl(s.url);
  const title = String(s.title || "");
  const alt = s.page ? (title ? `Page ${s.page} of ${title}` : `Page ${s.page}`) : title || "Cited page";
  // Full panel width, not capped in height: a page is taller than wide, and a height cap shrank
  // the table text (60 dpi, 510 px wide) below what can be read. The link opens the PDF.
  const img = (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      onError={() => setFailed(true)}
      width={510}
      height={660}
      className="h-auto w-full max-w-[510px] rounded-sm border bg-white"
    />
  );
  if (!href) return <div className="mt-2">{img}</div>;
  return (
    // Opens the PDF at the page, as the text link below it does; its link text is the
    // image's alt, so a screen reader hears "Page 37 of …" rather than a second
    // "Open the PDF at this page".
    <a href={href} target="_blank" rel="noopener" className="mt-2 block w-fit" title="Open the PDF at this page">
      {img}
    </a>
  );
}

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { source } from "@/panels/fixtures";
import { imageSrc, PageImage } from "@/panels/PageImage";

afterEach(cleanup);

describe("PageImage", () => {
  it("shows the page's image, lazily, linked to the PDF at that page", () => {
    render(<PageImage source={source(1, { image: "/pages/utilities/uam/11.jpg" })} />);
    const img = screen.getByRole("img");
    expect(img.getAttribute("src")).toBe("/pages/utilities/uam/11.jpg");
    expect(img.getAttribute("alt")).toBe("Page 11 of Utilities Accommodation Manual");
    expect(img.getAttribute("loading")).toBe("lazy");
    // No height cap: a capped page image is too small to read a table in.
    expect(img.className).not.toMatch(/max-h-/);
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("https://example.org/uam.pdf#page=11");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener");
  });

  it("shows nothing when the page has no image", () => {
    const { container } = render(<PageImage source={source(1, { image: null })} />);
    expect(container.innerHTML).toBe("");
  });

  it("hides the image once it fails to load", () => {
    render(<PageImage source={source(1, { image: "/pages/utilities/uam/11.jpg" })} />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows the image without a link when the PDF URL is not http(s)", () => {
    render(<PageImage source={source(1, { image: "/pages/utilities/uam/11.jpg", url: "javascript:alert(1)" })} />);
    expect(screen.getByRole("img")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("accepts only site-relative /pages/ paths as an image source", () => {
    expect(imageSrc("/pages/wztc/tmp-design-manual/37.jpg")).toBe("/pages/wztc/tmp-design-manual/37.jpg");
    for (const bad of ["https://evil.example/x.jpg", "//evil.example/x.jpg", "/pages/../index.html", "/pages/../secret.jpg", "data:image/png;base64,AAAA", 7, null]) {
      expect(imageSrc(bad)).toBeNull();
    }
  });
});

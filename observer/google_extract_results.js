() => {
  const blocks = Array.from(document.querySelectorAll("div#search div.g"));
  const picked = [];
  for (const block of blocks) {
    const anchor = block.querySelector("a[href]");
    const titleEl = block.querySelector("h3");
    if (!anchor || !titleEl) continue;
    const snippetEl = block.querySelector("div.VwiC3b, div.IsZvec, span.aCOpRe");
    picked.push({
      url: (anchor.getAttribute("href") || "").trim(),
      title: (titleEl.textContent || "").trim(),
      snippet: ((snippetEl && snippetEl.textContent) || "").trim(),
    });
  }

  if (picked.length > 0) {
    return picked;
  }

  const fallback = [];
  const links = Array.from(document.querySelectorAll("a[href]"));
  for (const link of links) {
    const titleEl = link.querySelector("h3");
    if (!titleEl) continue;
    fallback.push({
      url: (link.getAttribute("href") || "").trim(),
      title: (titleEl.textContent || "").trim(),
      snippet: "",
    });
  }
  return fallback;
};

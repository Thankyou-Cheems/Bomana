/** Keep resource paths inside the surface that serves the document. */
export function aircraftParametersURL(name: string, moduleURL: string, development: boolean,
  page: Pick<Location, "pathname" | "origin"> = globalThis.location): URL {
  if (!development && page?.pathname.startsWith("/app/")) {
    return new URL(`/app/shared/${name}`, page.origin);
  }
  const url = new URL(moduleURL);
  url.pathname = url.pathname.replace(/[^/]*$/, development ? "aircraft-parameters.json" : name);
  return url;
}

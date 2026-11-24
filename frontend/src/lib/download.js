// Save a Blob to the user's computer as `filename`. A browser can't write to
// disk directly, so point a temporary <a download> at an object URL for the
// blob, click it, then release the URL.
export function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

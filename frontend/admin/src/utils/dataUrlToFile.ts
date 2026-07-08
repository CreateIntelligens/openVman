export function dataUrlToFile(dataUrl: string, filename: string): File {
  const [header = "", body = ""] = dataUrl.split(",", 2);
  const mime = header.match(/:(.*?);/)?.[1] || "image/png";
  const binary = atob(body);
  const bytes = new Uint8Array(binary.length);

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  return new File([bytes], filename, { type: mime });
}

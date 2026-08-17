const SUPPORTED_MEDIA_EXTENSIONS = new Set([
  ".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv",
  ".jpg", ".jpeg", ".png", ".webp",
  ".wav", ".mp3", ".m4a",
]);

function isSupportedMedia(file) {
  const name = String(file?.name || "").toLowerCase();
  const dot = name.lastIndexOf(".");
  return dot >= 0 && SUPPORTED_MEDIA_EXTENSIONS.has(name.slice(dot));
}

export function filterMediaFiles(value) {
  const selected = Array.from(value || []);
  const files = selected.filter(isSupportedMedia);
  return {files, ignored: selected.length - files.length};
}

export function selectionSummary(value) {
  const result = filterMediaFiles(value);
  const size = Math.round(result.files.reduce((sum, file) => sum + file.size, 0) / 1024 / 1024);
  const ignoredText = result.ignored ? `；已忽略 ${result.ignored} 个非媒体文件` : "";
  if (result.files.length) {
    return `已选择 ${result.files.length} 个素材，共 ${size}MB${ignoredText}`;
  }
  return result.ignored ? `未找到支持的素材${ignoredText}` : "尚未选择";
}

/**
 * DropZone — file upload with drag-and-drop, click-to-browse, and client-side validation.
 * Accepts .docx, .pptx, and .md (markdown).  Submitting .md bypasses the
 * server-side pandoc dependency, which degrades the DOCX pipeline when
 * pandoc is unavailable.  20 MB size cap, inline errors.
 */

"use client";

import { useCallback, useState, useRef } from "react";
import { Upload, FileText, X } from "lucide-react";

const ACCEPTED_TYPES = [
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "text/markdown",
  "text/plain",
];
const ACCEPTED_EXTENSIONS = [".docx", ".pptx", ".md", ".markdown"];
const MAX_SIZE_BYTES = 20 * 1024 * 1024;

interface DropZoneProps {
  file: File | null;
  onFileSelect: (file: File | null) => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DropZone({ file, onFileSelect }: DropZoneProps) {
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validate = useCallback((f: File): string | null => {
    const ext = f.name.toLowerCase().slice(f.name.lastIndexOf("."));
    if (!ACCEPTED_EXTENSIONS.includes(ext) && !ACCEPTED_TYPES.includes(f.type)) {
      return "Only .docx, .pptx, and .md files are accepted.";
    }
    if (f.size > MAX_SIZE_BYTES) {
      return `File too large (${formatSize(f.size)}). Maximum is 20 MB.`;
    }
    return null;
  }, []);

  const handleFile = useCallback(
    (f: File) => {
      const err = validate(f);
      if (err) {
        setError(err);
        onFileSelect(null);
      } else {
        setError(null);
        onFileSelect(f);
      }
    },
    [validate, onFileSelect]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files[0];
      if (f) handleFile(f);
    },
    [handleFile]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      if (f) handleFile(f);
    },
    [handleFile]
  );

  const clearFile = useCallback(() => {
    setError(null);
    onFileSelect(null);
    if (inputRef.current) inputRef.current.value = "";
  }, [onFileSelect]);

  return (
    <div className="space-y-2">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`
          relative flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed
          px-6 py-12 cursor-pointer transition-colors
          ${
            dragOver
              ? "border-ring bg-accent"
              : file
              ? "border-success/50 bg-success/5"
              : "border-border hover:border-muted-foreground/40 hover:bg-accent/50"
          }
        `}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".docx,.pptx,.md,.markdown"
          onChange={handleChange}
          className="hidden"
        />

        {file ? (
          <div className="flex items-center gap-3">
            <FileText className="h-8 w-8 text-success" />
            <div>
              <p className="text-sm font-medium text-foreground">
                {file.name}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatSize(file.size)}
              </p>
            </div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                clearFile();
              }}
              className="ml-2 rounded-md p-1 hover:bg-muted transition-colors"
            >
              <X className="h-4 w-4 text-muted-foreground" />
            </button>
          </div>
        ) : (
          <>
            <Upload className="h-8 w-8 text-muted-foreground" />
            <div className="text-center">
              <p className="text-sm font-medium text-foreground">
                Drop your document here
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                .docx, .pptx, or .md &mdash; max 20 MB
              </p>
            </div>
            <button
              type="button"
              className="mt-1 rounded-md bg-secondary px-4 py-1.5 text-xs font-medium text-secondary-foreground hover:bg-secondary/80 transition-colors"
            >
              Browse files
            </button>
          </>
        )}
      </div>

      {error && (
        <p className="text-sm text-destructive font-medium">{error}</p>
      )}
    </div>
  );
}

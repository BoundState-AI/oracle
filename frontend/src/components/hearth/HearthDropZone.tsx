/**
 * HearthDropZone — document upload for the DocScrubber.
 *
 * Derived from the Oracle DropZone but intentionally separate: HEARTH's
 * accept list (.pdf/.docx/.txt/.md) and 16 MB cap mirror the scrubber
 * backend contract (MAX_DOCUMENT_BYTES, SUPPORTED_SUFFIXES) and must be
 * able to drift from Oracle's pipeline without coupling the two.
 */

"use client";

import { useCallback, useRef, useState } from "react";
import { FileText, Upload, X } from "lucide-react";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"];
// Mirrors the backend MAX_DOCUMENT_BYTES — the server remains the authority.
const MAX_SIZE_BYTES = 16 * 1024 * 1024;

interface HearthDropZoneProps {
  file: File | null;
  onFileSelect: (file: File | null) => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function HearthDropZone({ file, onFileSelect }: HearthDropZoneProps) {
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (candidate: File) => {
      const ext = candidate.name
        .toLowerCase()
        .slice(candidate.name.lastIndexOf("."));
      if (!ACCEPTED_EXTENSIONS.includes(ext)) {
        setError("Only .pdf, .docx, .txt, and .md documents are accepted.");
        onFileSelect(null);
        return;
      }
      if (candidate.size > MAX_SIZE_BYTES) {
        setError(
          `File too large (${formatSize(candidate.size)}). Maximum is 16 MB.`
        );
        onFileSelect(null);
        return;
      }
      setError(null);
      onFileSelect(candidate);
    },
    [onFileSelect]
  );

  const clearFile = useCallback(() => {
    setError(null);
    onFileSelect(null);
    if (inputRef.current) inputRef.current.value = "";
  }, [onFileSelect]);

  return (
    <div className="space-y-2">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragOver(false);
          const dropped = event.dataTransfer.files[0];
          if (dropped) handleFile(dropped);
        }}
        onClick={() => inputRef.current?.click()}
        className={`relative flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-10 cursor-pointer transition-colors ${
          dragOver
            ? "border-amber-400/70 bg-amber-400/5"
            : file
            ? "border-success/50 bg-success/5"
            : "border-border hover:border-muted-foreground/40 hover:bg-accent/50"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.txt,.md"
          onChange={(event) => {
            const selected = event.target.files?.[0];
            if (selected) handleFile(selected);
          }}
          className="hidden"
        />

        {file ? (
          <div className="flex items-center gap-3">
            <FileText className="h-8 w-8 text-success" />
            <div>
              <p className="text-sm font-medium text-foreground">{file.name}</p>
              <p className="text-xs text-muted-foreground">
                {formatSize(file.size)}
              </p>
            </div>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
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
                Drop the agreement or contract here
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                .pdf, .docx, .txt, or .md &mdash; max 16 MB
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

      {error && <p className="text-sm text-destructive font-medium">{error}</p>}
    </div>
  );
}

"use client";

import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { RotateCcw, ArrowRight } from "lucide-react";

interface CritiquePanelProps {
  critique: string;
  onStartOver: () => void;
  onGenerate: () => void;
  generating: boolean;
}

export function CritiquePanel({
  critique,
  onStartOver,
  onGenerate,
  generating,
}: CritiquePanelProps) {
  return (
    <Card className="border-border">
      <CardHeader>
        <CardTitle className="text-lg font-semibold tracking-tight">
          Oracle Review
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="max-h-[28rem] overflow-y-auto rounded-md border border-border bg-muted/30 p-4">
          <div className="prose prose-sm dark:prose-invert max-w-none text-foreground prose-headings:text-foreground prose-strong:text-foreground prose-li:text-foreground">
            <ReactMarkdown>{critique}</ReactMarkdown>
          </div>
        </div>
      </CardContent>
      <CardFooter className="flex justify-between gap-3">
        <Button variant="outline" onClick={onStartOver} disabled={generating}>
          <RotateCcw className="h-4 w-4" data-icon="inline-start" />
          Start Over
        </Button>
        <Button onClick={onGenerate} disabled={generating}>
          {generating ? "Generating..." : "Generate Documents"}
          {!generating && <ArrowRight className="h-4 w-4" data-icon="inline-end" />}
        </Button>
      </CardFooter>
    </Card>
  );
}

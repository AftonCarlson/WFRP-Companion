import { RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../../lib/apiError";
import {
  getDocument,
  type PDFDocumentLoadingTask,
  type PDFDocumentProxy,
  type RenderTask,
} from "../../lib/pdfjs";
import { pdfUrlForBook } from "../../lib/pdfUrl";
import type { PdfTab } from "../../state/workspaceState";

export type PdfCanvasProps = {
  tab: PdfTab;
};

type RenderStatus = "idle" | "loading" | "rendering" | "ready" | "error";

export function PdfCanvas({ tab }: PdfCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState<RenderStatus>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [renderAttempt, setRenderAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let loadingTask: PDFDocumentLoadingTask | null = null;
    let documentProxy: PDFDocumentProxy | null = null;
    let renderTask: RenderTask | null = null;

    async function renderPage() {
      setStatus("loading");
      setMessage(null);

      try {
        loadingTask = getDocument({ url: pdfUrlForBook(tab.bookId) });
        documentProxy = await loadingTask.promise;
        if (cancelled) {
          return;
        }

        const pageNumber = Math.min(
          Math.max(tab.pageNumber, 1),
          documentProxy.numPages,
        );
        const page = await documentProxy.getPage(pageNumber);
        if (cancelled) {
          return;
        }

        const canvas = canvasRef.current;
        const canvasContext = canvas?.getContext("2d");
        if (!canvas || !canvasContext) {
          throw new Error("Unable to create PDF canvas context.");
        }

        const viewport = page.getViewport({ scale: tab.zoom });
        const outputScale = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * outputScale);
        canvas.height = Math.floor(viewport.height * outputScale);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;

        setStatus("rendering");
        renderTask = page.render({
          canvas,
          canvasContext,
          viewport,
          transform:
            outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
        });
        await renderTask.promise;

        if (!cancelled) {
          setStatus("ready");
        }
      } catch (error) {
        if (!cancelled) {
          setStatus("error");
          setMessage(errorMessage(error));
        }
      }
    }

    void renderPage();

    return () => {
      cancelled = true;
      renderTask?.cancel();
      void loadingTask?.destroy();
      void documentProxy?.cleanup();
    };
  }, [tab.bookId, tab.pageNumber, tab.zoom, renderAttempt]);

  return (
    <div className="pdf-canvas" aria-live="polite">
      {status === "loading" || status === "rendering" ? (
        <div className="pdf-canvas__status">
          {status === "loading" ? "Loading PDF..." : "Rendering page..."}
        </div>
      ) : null}
      {status === "error" ? (
        <div className="pdf-canvas__status pdf-canvas__status--error">
          <span>{message ?? "Unable to render PDF page."}</span>
          <button
            aria-label="Retry PDF render"
            onClick={() => setRenderAttempt((attempt) => attempt + 1)}
            type="button"
          >
            <RotateCw aria-hidden="true" size={14} />
            Retry
          </button>
        </div>
      ) : null}
      <canvas ref={canvasRef} aria-label={`${tab.title} page ${tab.pageNumber}`} />
    </div>
  );
}

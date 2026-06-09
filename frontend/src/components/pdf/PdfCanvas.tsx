import { RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../../lib/apiError";
import { visiblePdfPages } from "../../lib/pdfPages";
import {
  getDocument,
  type PDFDocumentLoadingTask,
  type PDFDocumentProxy,
  type RenderTask,
} from "../../lib/pdfjs";
import { pdfUrlForBook } from "../../lib/pdfUrl";
import type { PdfTab } from "../../state/workspaceState";

export type PdfCanvasProps = {
  onDocumentLoaded?: (pageCount: number) => void;
  tab: PdfTab;
};

type RenderStatus = "idle" | "loading" | "rendering" | "ready" | "error";

export function PdfCanvas({ onDocumentLoaded, tab }: PdfCanvasProps) {
  const canvasRefs = useRef<Record<number, HTMLCanvasElement | null>>({});
  const documentRef = useRef<PDFDocumentProxy | null>(null);
  const loadingTaskRef = useRef<PDFDocumentLoadingTask | null>(null);
  const onDocumentLoadedRef = useRef(onDocumentLoaded);
  const renderTasksRef = useRef<RenderTask[]>([]);
  const [pageCount, setPageCount] = useState<number | null>(null);
  const [status, setStatus] = useState<RenderStatus>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [renderAttempt, setRenderAttempt] = useState(0);

  useEffect(() => {
    onDocumentLoadedRef.current = onDocumentLoaded;
  }, [onDocumentLoaded]);

  useEffect(() => {
    let cancelled = false;

    async function loadDocument() {
      setStatus("loading");
      setMessage(null);
      setPageCount(null);
      documentRef.current = null;

      try {
        const loadingTask = getDocument({ url: pdfUrlForBook(tab.bookId) });
        loadingTaskRef.current = loadingTask;
        const documentProxy = await loadingTask.promise;
        if (cancelled) {
          return;
        }
        documentRef.current = documentProxy;
        onDocumentLoadedRef.current?.(documentProxy.numPages);
        setPageCount(documentProxy.numPages);
      } catch (error) {
        if (!cancelled) {
          setStatus("error");
          setMessage(errorMessage(error));
        }
      }
    }

    void loadDocument();

    return () => {
      cancelled = true;
      cancelRenderTasks();
      void loadingTaskRef.current?.destroy();
      void documentRef.current?.cleanup();
      loadingTaskRef.current = null;
      documentRef.current = null;
    };
  }, [tab.bookId, renderAttempt]);

  const visiblePages = visiblePdfPages(
    tab.pageNumber,
    pageCount ?? tab.pageNumber,
    tab.viewMode,
  );
  const visiblePageKey = visiblePages.join(",");

  useEffect(() => {
    let cancelled = false;

    async function renderPages() {
      const documentProxy = documentRef.current;
      if (!documentProxy || pageCount === null) {
        return;
      }
      cancelRenderTasks();
      setStatus("rendering");
      setMessage(null);

      try {
        await Promise.all(
          visiblePages.map(async (pageNumber) => {
            const page = await documentProxy.getPage(pageNumber);
            if (cancelled) {
              return;
            }

            const canvas = canvasRefs.current[pageNumber];
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

            const renderTask = page.render({
              canvas,
              canvasContext,
              viewport,
              transform:
                outputScale === 1
                  ? undefined
                  : [outputScale, 0, 0, outputScale, 0, 0],
            });
            renderTasksRef.current.push(renderTask);
            await renderTask.promise;
          }),
        );

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

    void renderPages();

    return () => {
      cancelled = true;
      cancelRenderTasks();
    };
  }, [pageCount, tab.zoom, visiblePageKey]);

  return (
    <div className={`pdf-canvas pdf-canvas--${tab.viewMode}`} aria-live="polite">
      {status === "loading" || status === "rendering" ? (
        <div className="pdf-canvas__status">
          {status === "loading" ? "Loading PDF..." : "Rendering page..."}
        </div>
      ) : null}
      {status === "error" ? (
        <div className="pdf-canvas__status pdf-canvas__status--error">
          <span>{message}</span>
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
      <div className="pdf-canvas__pages">
        {visiblePages.map((pageNumber) => (
          <canvas
            aria-label={`${tab.title} page ${pageNumber}`}
            key={pageNumber}
            ref={(canvas) => {
              canvasRefs.current[pageNumber] = canvas;
            }}
          />
        ))}
      </div>
    </div>
  );

  function cancelRenderTasks() {
    for (const task of renderTasksRef.current) {
      task.cancel();
    }
    renderTasksRef.current = [];
  }
}

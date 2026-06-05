import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { pdfUrlForBook } from "../../lib/pdfUrl";
import type { PdfTab } from "../../state/workspaceState";
import { renderApp } from "../../test/render";
import { PdfCanvas } from "./PdfCanvas";

const getDocument = vi.fn();
const originalDevicePixelRatio = window.devicePixelRatio;

vi.mock("../../lib/pdfjs", () => ({
  getDocument: (...args: unknown[]) => getDocument(...args),
}));

const tab: PdfTab = {
  id: "core-rules",
  bookId: "core-rules",
  title: "Core Rules",
  pageNumber: 2,
  zoom: 1.25,
  viewMode: "single",
};

function renderTask() {
  return {
    cancel: vi.fn(),
    promise: Promise.resolve(),
  };
}

function documentLoadingTask({
  render = renderTask(),
  destroy = vi.fn().mockResolvedValue(undefined),
  cleanup = vi.fn().mockResolvedValue(undefined),
} = {}) {
  const getViewport = vi.fn().mockReturnValue({ width: 200, height: 300 });
  const renderPage = vi.fn().mockReturnValue(render);
  const getPage = vi.fn().mockResolvedValue({
    getViewport,
    render: renderPage,
  });
  return {
    destroy,
    documentProxy: {
      cleanup,
      getPage,
      numPages: 10,
    },
    getPage,
    getViewport,
    loadingTask: null as unknown,
    render,
    renderPage,
  };
}

beforeEach(() => {
  HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue({});
});

afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(window, "devicePixelRatio", {
    configurable: true,
    value: originalDevicePixelRatio,
  });
  getDocument.mockReset();
});

describe("PdfCanvas", () => {
  it("loads and renders the selected PDF page through the guarded API URL", async () => {
    Object.defineProperty(window, "devicePixelRatio", {
      configurable: true,
      value: 2,
    });
    const task = documentLoadingTask();
    const loadingTask = {
      destroy: task.destroy,
      promise: Promise.resolve(task.documentProxy),
    };
    task.loadingTask = loadingTask;
    getDocument.mockReturnValue(loadingTask);

    const onDocumentLoaded = vi.fn();
    const { unmount } = renderApp(
      <PdfCanvas tab={tab} onDocumentLoaded={onDocumentLoaded} />,
    );

    await waitFor(() =>
      expect(task.renderPage).toHaveBeenCalledWith(
        expect.objectContaining({
          canvas: expect.any(HTMLCanvasElement),
          canvasContext: expect.any(Object),
          transform: [2, 0, 0, 2, 0, 0],
          viewport: { width: 200, height: 300 },
        }),
      ),
    );
    expect(getDocument).toHaveBeenCalledWith({ url: pdfUrlForBook("core-rules") });
    expect(onDocumentLoaded).toHaveBeenCalledWith(10);
    expect(task.getPage).toHaveBeenCalledWith(2);
    expect(task.getViewport).toHaveBeenCalledWith({ scale: 1.25 });

    unmount();

    expect(task.render.cancel).toHaveBeenCalledOnce();
    expect(task.destroy).toHaveBeenCalledOnce();
    expect(task.documentProxy.cleanup).toHaveBeenCalledOnce();
  });

  it("renders two-page spreads after the first two pages", async () => {
    const task = documentLoadingTask();
    getDocument.mockReturnValue({
      destroy: task.destroy,
      promise: Promise.resolve(task.documentProxy),
    });

    renderApp(
      <PdfCanvas tab={{ ...tab, pageNumber: 3, viewMode: "two-page" }} />,
    );

    await waitFor(() => expect(task.getPage).toHaveBeenCalledWith(3));
    expect(task.getPage).toHaveBeenCalledWith(4);
    expect(screen.getByLabelText("Core Rules page 3")).toBeInTheDocument();
    expect(screen.getByLabelText("Core Rules page 4")).toBeInTheDocument();
  });

  it("renders the first two pages alone in two-page mode", async () => {
    const task = documentLoadingTask();
    getDocument.mockReturnValue({
      destroy: task.destroy,
      promise: Promise.resolve(task.documentProxy),
    });

    renderApp(<PdfCanvas tab={{ ...tab, pageNumber: 1, viewMode: "two-page" }} />);

    await waitFor(() => expect(task.getPage).toHaveBeenCalledWith(1));
    expect(task.getPage).toHaveBeenCalledTimes(1);

    getDocument.mockClear();
    task.getPage.mockClear();

    renderApp(<PdfCanvas tab={{ ...tab, pageNumber: 2, viewMode: "two-page" }} />);

    await waitFor(() => expect(task.getPage).toHaveBeenCalledWith(2));
    expect(task.getPage).toHaveBeenCalledTimes(1);
  });

  it("renders an unpaired final page alone in two-page mode", async () => {
    const task = documentLoadingTask();
    task.documentProxy.numPages = 9;
    getDocument.mockReturnValue({
      destroy: task.destroy,
      promise: Promise.resolve(task.documentProxy),
    });

    renderApp(<PdfCanvas tab={{ ...tab, pageNumber: 9, viewMode: "two-page" }} />);

    await waitFor(() => expect(task.getPage).toHaveBeenCalledWith(9));
    expect(task.getPage).toHaveBeenCalledTimes(1);
  });

  it("renders without a high-DPI transform when device scale is one", async () => {
    Object.defineProperty(window, "devicePixelRatio", {
      configurable: true,
      value: 1,
    });
    const task = documentLoadingTask();
    getDocument.mockReturnValue({
      destroy: task.destroy,
      promise: Promise.resolve(task.documentProxy),
    });

    renderApp(<PdfCanvas tab={tab} />);

    await waitFor(() =>
      expect(task.renderPage).toHaveBeenCalledWith(
        expect.objectContaining({
          transform: undefined,
        }),
      ),
    );
  });

  it("falls back to standard pixel scale when the browser ratio is unavailable", async () => {
    Object.defineProperty(window, "devicePixelRatio", {
      configurable: true,
      value: 0,
    });
    const task = documentLoadingTask();
    getDocument.mockReturnValue({
      destroy: task.destroy,
      promise: Promise.resolve(task.documentProxy),
    });

    renderApp(<PdfCanvas tab={tab} />);

    await waitFor(() =>
      expect(task.renderPage).toHaveBeenCalledWith(
        expect.objectContaining({
          transform: undefined,
        }),
      ),
    );
  });

  it("shows render errors and retries loading the PDF", async () => {
    const user = userEvent.setup();
    getDocument
      .mockReturnValueOnce({
        destroy: vi.fn(),
        promise: Promise.reject(new Error("PDF unavailable")),
      })
      .mockReturnValueOnce({
        destroy: vi.fn(),
        promise: Promise.resolve(documentLoadingTask().documentProxy),
      });

    renderApp(<PdfCanvas tab={tab} />);

    expect(await screen.findByText("PDF unavailable")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry PDF render" }));

    await waitFor(() => expect(getDocument).toHaveBeenCalledTimes(2));
  });

  it("reports a missing canvas context as a render error", async () => {
    HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue(null);
    getDocument.mockReturnValue({
      destroy: vi.fn(),
      promise: Promise.resolve(documentLoadingTask().documentProxy),
    });

    renderApp(<PdfCanvas tab={tab} />);

    expect(
      await screen.findByText("Unable to create PDF canvas context."),
    ).toBeInTheDocument();
  });

  it("does not render after unmounting before document load resolves", async () => {
    const task = documentLoadingTask();
    let resolveDocument: (value: typeof task.documentProxy) => void = () => {};
    const loadingTask = {
      destroy: vi.fn(),
      promise: new Promise<typeof task.documentProxy>((resolve) => {
        resolveDocument = resolve;
      }),
    };
    getDocument.mockReturnValue(loadingTask);

    const { unmount } = renderApp(<PdfCanvas tab={tab} />);
    unmount();
    resolveDocument(task.documentProxy);
    await Promise.resolve();

    expect(task.getPage).not.toHaveBeenCalled();
    expect(loadingTask.destroy).toHaveBeenCalledOnce();
  });

  it("does not show load errors after unmounting before document load rejects", async () => {
    let rejectDocument: (reason?: unknown) => void = () => {};
    const loadingTask = {
      destroy: vi.fn(),
      promise: new Promise((_, reject) => {
        rejectDocument = reject;
      }),
    };
    getDocument.mockReturnValue(loadingTask);

    const { unmount } = renderApp(<PdfCanvas tab={tab} />);
    unmount();
    rejectDocument(new Error("Late load failure"));
    await Promise.resolve();

    expect(screen.queryByText("Late load failure")).not.toBeInTheDocument();
    expect(loadingTask.destroy).toHaveBeenCalledOnce();
  });

  it("does not render after unmounting before page load resolves", async () => {
    let resolvePage: (value: {
      getViewport: () => { width: number; height: number };
      render: () => ReturnType<typeof renderTask>;
    }) => void = () => {};
    const getPage = vi.fn(
      () =>
        new Promise<{
          getViewport: () => { width: number; height: number };
          render: () => ReturnType<typeof renderTask>;
        }>((resolve) => {
          resolvePage = resolve;
        }),
    );
    const page = {
      getViewport: vi.fn().mockReturnValue({ width: 200, height: 300 }),
      render: vi.fn().mockReturnValue(renderTask()),
    };
    const loadingTask = {
      destroy: vi.fn(),
      promise: Promise.resolve({
        cleanup: vi.fn(),
        getPage,
        numPages: 10,
      }),
    };
    getDocument.mockReturnValue(loadingTask);

    const { unmount } = renderApp(<PdfCanvas tab={tab} />);
    await waitFor(() => expect(getPage).toHaveBeenCalledWith(2));
    unmount();
    resolvePage(page);
    await Promise.resolve();

    expect(page.render).not.toHaveBeenCalled();
    expect(loadingTask.destroy).toHaveBeenCalledOnce();
  });

  it("does not show render errors after unmounting before render rejects", async () => {
    let rejectRender: (reason?: unknown) => void = () => {};
    const render = {
      cancel: vi.fn(),
      promise: new Promise<void>((_, reject) => {
        rejectRender = reject;
      }),
    };
    const task = documentLoadingTask({ render });
    getDocument.mockReturnValue({
      destroy: task.destroy,
      promise: Promise.resolve(task.documentProxy),
    });

    const { unmount } = renderApp(<PdfCanvas tab={tab} />);
    await waitFor(() => expect(task.renderPage).toHaveBeenCalled());
    unmount();
    rejectRender(new Error("Late render failure"));
    await Promise.resolve();

    expect(screen.queryByText("Late render failure")).not.toBeInTheDocument();
    expect(render.cancel).toHaveBeenCalledOnce();
  });
});

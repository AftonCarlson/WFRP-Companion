import { useEffect, useState } from "react";

import { AppShell } from "./components/AppShell";
import {
  AgentChatHeaderControls,
  AgentChatPanel,
} from "./components/chat/AgentChatPanel";
import { LibrarySearchPanel } from "./components/library/LibrarySearchPanel";
import {
  PdfReaderControls,
  PdfReaderPanel,
} from "./components/pdf/PdfReaderPanel";
import { useInitialWorkspaceData } from "./hooks/useInitialWorkspaceData";
import type { SourceSetBookResponse } from "./types/api";
import "./App.css";

export default function App() {
  const { data, error, loading } = useInitialWorkspaceData();
  const [chatHistoryOpen, setChatHistoryOpen] = useState(false);
  const [sourceSetBooks, setSourceSetBooks] = useState<
    SourceSetBookResponse[]
  >([]);

  useEffect(() => {
    setSourceSetBooks(data?.sourceSetBooks ?? []);
  }, [data?.sourceSetBooks]);

  const enabledBookCount = sourceSetBooks.filter((book) => book.enabled).length;

  function handleSourceSetBookUpdated(updatedBook: SourceSetBookResponse) {
    setSourceSetBooks((currentBooks) =>
      currentBooks.map((book) =>
        book.book_id === updatedBook.book_id ? updatedBook : book,
      ),
    );
  }

  return (
    <AppShell
      agent={() => <AgentChatPanel historyOpen={chatHistoryOpen} />}
      agentHeaderControls={() => (
        <AgentChatHeaderControls
          historyOpen={chatHistoryOpen}
          setHistoryOpen={setChatHistoryOpen}
        />
      )}
      enabledBookCount={enabledBookCount}
      error={error}
      left={(context) => (
        <LibrarySearchPanel
          activeSourceSetId={data?.activeSourceSetId ?? null}
          books={data?.books ?? []}
          collapsedCategories={context.layout.collapsedLibraryCategories}
          leftTab={context.layout.leftTab}
          onOpenPdfPage={({ bookId, title, pageNumber }) =>
            context.openPdfTab({ bookId, title, pageNumber })
          }
          onSetLeftTab={context.setLeftTab}
          onSourceSetBookUpdated={handleSourceSetBookUpdated}
          onToggleCategory={context.toggleLibraryCategory}
          sourceSetBooks={sourceSetBooks}
        />
      )}
      loading={loading}
      reader={(context) => (
        <PdfReaderPanel
          activeTabId={context.layout.activePdfTabId}
          onCloseTab={context.closePdfTab}
          onSelectTab={context.selectPdfTab}
          onSetPage={context.setPdfTabPage}
          openTabs={context.layout.openPdfTabs}
        />
      )}
      readerHeaderControls={(context) => (
        <PdfReaderControls
          activeTabId={context.layout.activePdfTabId}
          onSetPage={context.setPdfTabPage}
          onSetViewMode={context.setPdfTabViewMode}
          onSetZoom={context.setPdfTabZoom}
          openTabs={context.layout.openPdfTabs}
        />
      )}
    />
  );
}

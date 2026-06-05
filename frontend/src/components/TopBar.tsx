import { Library, Settings, SlidersHorizontal, Wrench } from "lucide-react";

export type TopBarProps = {
  enabledBookCount: number;
  onFocusLibrary?: () => void;
  onToggleViewMenu?: () => void;
  viewMenuOpen?: boolean;
};

export function TopBar({
  enabledBookCount,
  onFocusLibrary,
  onToggleViewMenu,
  viewMenuOpen = false,
}: TopBarProps) {
  return (
    <header className="top-bar">
      <strong>WFRP Companion</strong>
      <nav aria-label="Global controls">
        <button
          aria-controls="view-popover"
          aria-expanded={viewMenuOpen}
          type="button"
          onClick={onToggleViewMenu}
        >
          <SlidersHorizontal aria-hidden="true" size={15} />
          View
        </button>
        <button type="button" onClick={onFocusLibrary}>
          <Library aria-hidden="true" size={15} />
          Library
        </button>
        <button type="button" disabled>
          <Wrench aria-hidden="true" size={15} />
          Tools
        </button>
        <button type="button" disabled>
          <Settings aria-hidden="true" size={15} />
          Settings
        </button>
      </nav>
      <button
        className="top-bar__status"
        type="button"
        onClick={onFocusLibrary}
      >
        {enabledBookCount} books enabled
      </button>
    </header>
  );
}

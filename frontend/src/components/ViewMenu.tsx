import { RotateCcw } from "lucide-react";

export type ViewMenuProps = {
  onResetLayout: () => void;
};

export function ViewMenu({ onResetLayout }: ViewMenuProps) {
  return (
    <div className="view-menu" id="view-popover" aria-label="View options">
      <button type="button" onClick={onResetLayout}>
        <RotateCcw aria-hidden="true" size={15} />
        Reset layout
      </button>
    </div>
  );
}

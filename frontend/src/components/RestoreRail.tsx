export type RestoreRailProps = {
  label: string;
  onRestore: () => void;
};

export function RestoreRail({ label, onRestore }: RestoreRailProps) {
  return (
    <button className="restore-rail" type="button" onClick={onRestore}>
      {label}
    </button>
  );
}

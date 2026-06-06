import { Fragment, type ReactNode } from "react";

export type MarkdownTextProps = {
  content: string;
};

type TableBlock = {
  headers: string[];
  rows: string[][];
};

export function MarkdownText({ content }: MarkdownTextProps) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      index += 1;
      continue;
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = Math.min(4, heading[1].length + 1);
      const Tag = `h${level}` as "h2" | "h3" | "h4" | "h5";
      blocks.push(<Tag key={blocks.length}>{parseInline(heading[2])}</Tag>);
      index += 1;
      continue;
    }

    const table = readTable(lines, index);
    if (table) {
      blocks.push(<MarkdownTable key={blocks.length} table={table.block} />);
      index = table.nextIndex;
      continue;
    }

    const unordered = readList(lines, index, /^[-*]\s+(.+)$/);
    if (unordered) {
      blocks.push(
        <ul key={blocks.length}>
          {unordered.items.map((item, itemIndex) => (
            <li key={itemIndex}>{parseInline(item)}</li>
          ))}
        </ul>,
      );
      index = unordered.nextIndex;
      continue;
    }

    const ordered = readList(lines, index, /^\d+\.\s+(.+)$/);
    if (ordered) {
      blocks.push(
        <ol key={blocks.length}>
          {ordered.items.map((item, itemIndex) => (
            <li key={itemIndex}>{parseInline(item)}</li>
          ))}
        </ol>,
      );
      index = ordered.nextIndex;
      continue;
    }

    const paragraphLines = [];
    while (index < lines.length && lines[index].trim()) {
      if (
        index !== lines.length - 1 &&
        readTable(lines, index) !== null
      ) {
        break;
      }
      const nextTrimmed = lines[index].trim();
      if (
        nextTrimmed.match(/^(#{1,4})\s+(.+)$/) ||
        nextTrimmed.match(/^[-*]\s+(.+)$/) ||
        nextTrimmed.match(/^\d+\.\s+(.+)$/)
      ) {
        break;
      }
      paragraphLines.push(nextTrimmed);
      index += 1;
    }

    if (paragraphLines.length) {
      blocks.push(
        <p key={blocks.length}>{parseInline(paragraphLines.join(" "))}</p>,
      );
    } else {
      index += 1;
    }
  }

  return <div className="agent-chat__markdown">{blocks}</div>;
}

function MarkdownTable({ table }: { table: TableBlock }) {
  return (
    <div className="agent-chat__table-wrap">
      <table>
        <thead>
          <tr>
            {table.headers.map((header, index) => (
              <th key={index}>{parseInline(header)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {table.headers.map((_, cellIndex) => (
                <td key={cellIndex}>{parseInline(row[cellIndex] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function readTable(lines: string[], startIndex: number) {
  if (startIndex + 1 >= lines.length) {
    return null;
  }
  const headers = parseTableRow(lines[startIndex]);
  const separator = parseTableRow(lines[startIndex + 1]);
  if (
    headers.length < 2 ||
    separator.length !== headers.length ||
    !separator.every((cell) => /^:?-{3,}:?$/.test(cell.trim()))
  ) {
    return null;
  }

  const rows: string[][] = [];
  let index = startIndex + 2;
  while (index < lines.length) {
    const row = parseTableRow(lines[index]);
    if (row.length !== headers.length) {
      break;
    }
    rows.push(row);
    index += 1;
  }

  return {
    block: { headers, rows },
    nextIndex: index,
  };
}

function parseTableRow(line: string) {
  const trimmed = line.trim();
  if (!trimmed.includes("|")) {
    return [];
  }
  return trimmed
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function readList(lines: string[], startIndex: number, pattern: RegExp) {
  const items: string[] = [];
  let index = startIndex;
  while (index < lines.length) {
    const match = lines[index].trim().match(pattern);
    if (!match) {
      break;
    }
    items.push(match[1]);
    index += 1;
  }
  if (!items.length) {
    return null;
  }
  return { items, nextIndex: index };
}

function parseInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index));
    }
    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(
        <strong key={nodes.length}>{token.slice(2, -2)}</strong>,
      );
    } else {
      nodes.push(<code key={nodes.length}>{token.slice(1, -1)}</code>);
    }
    cursor = match.index + token.length;
  }
  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }
  return nodes.map((node, index) => <Fragment key={index}>{node}</Fragment>);
}

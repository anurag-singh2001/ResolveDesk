import type { ReactNode } from "react";

type Block = { kind: "p"; text: string } | { kind: "ul"; items: string[] };

const BULLET = /^\s*[-*]\s+(.*)$/;

/** Split policy text into paragraphs and bullet lists. Nothing is interpreted as HTML or
 *  markdown: every string below ends up as a React text node, so markup in policy text (which
 *  is untrusted, hard rule 9) shows as literal characters. */
export function parsePlainBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) blocks.push({ kind: "p", text: para.join(" ") });
    para = [];
  };
  for (const line of text.replace(/\r\n?/g, "\n").split("\n")) {
    const bullet = BULLET.exec(line);
    if (bullet) {
      flush();
      const last = blocks[blocks.length - 1];
      if (last && last.kind === "ul") last.items.push(bullet[1]);
      else blocks.push({ kind: "ul", items: [bullet[1]] });
    } else if (line.trim() === "") {
      flush();
    } else {
      para.push(line.trim());
    }
  }
  flush();
  return blocks;
}

export function PlainPolicyText({ text }: { text: string }): ReactNode {
  return (
    <div className="space-y-2 text-sm text-muted-foreground" data-testid="policy-text">
      {parsePlainBlocks(text).map((b, i) =>
        b.kind === "p" ? (
          <p key={i}>{b.text}</p>
        ) : (
          <ul key={i} className="list-disc space-y-1 pl-5">
            {b.items.map((item, j) => (
              <li key={j}>{item}</li>
            ))}
          </ul>
        ),
      )}
    </div>
  );
}

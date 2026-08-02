import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

/**
 * The agent's answers ALWAYS include markdown tables for any tabular data
 * (price series, BCTC comparisons, news lists -- see synthesize_node.py's
 * system prompt, which explicitly instructs the LLM to always render
 * `series`/`results`/`periods` as a markdown table). Rendering that as raw
 * text with literal "|" characters would be a real regression vs. the old
 * Streamlit UI (which used `st.markdown`, a full markdown renderer) -- gfm
 * table support here is not optional.
 */
export function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none prose-p:leading-relaxed prose-headings:mt-4 prose-headings:mb-2 prose-table:my-2">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ ...props }) => (
            <div className="my-3 overflow-hidden rounded-md border">
              <Table {...props} />
            </div>
          ),
          thead: ({ ...props }) => <TableHeader {...props} />,
          tbody: ({ ...props }) => <TableBody {...props} />,
          tr: ({ ...props }) => <TableRow {...props} />,
          th: ({ className, ...props }) => (
            <TableHead className={cn("whitespace-normal", className)} {...props} />
          ),
          td: ({ className, ...props }) => (
            <TableCell className={cn("whitespace-normal", className)} {...props} />
          ),
          a: ({ ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

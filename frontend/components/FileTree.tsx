import { createContext, useContext, useEffect, useState } from "react";

interface Props {
  files: string[];
}

function buildTree(paths: string[]): Record<string, any> {
  const root: Record<string, any> = {};
  for (const path of paths) {
    const parts = path.split("/");
    let node = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      if (!node[part]) {
        node[part] = i === parts.length - 1 ? null : {};
      }
      if (node[part] !== null) {
        node = node[part];
      }
    }
  }
  return root;
}

// Context so the "expand all / collapse all" buttons can reach every TreeNode
const TreeStateCtx = createContext<{ globalOpen: boolean | null }>({ globalOpen: null });

function TreeNode({ name, node, depth }: { name: string; node: any; depth: number }) {
  const { globalOpen } = useContext(TreeStateCtx);
  const [open, setOpen] = useState(depth < 2);
  const isDir = node !== null && typeof node === "object";

  // Sync local state when the user hits "expand all" / "collapse all"
  useEffect(() => {
    if (globalOpen !== null) setOpen(globalOpen);
  }, [globalOpen]);

  if (!isDir) {
    return (
      <div className="flex items-center gap-1.5 py-0.5" style={{ paddingLeft: `${depth * 16}px` }}>
        <svg className="h-3.5 w-3.5 text-slate-400 dark:text-slate-500 shrink-0" viewBox="0 0 20 20" fill="currentColor">
          <path d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" />
        </svg>
        <span className="text-xs font-mono text-slate-600 dark:text-slate-400 truncate">{name}</span>
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 py-0.5 hover:text-blue-700 dark:hover:text-blue-300 w-full text-left"
        style={{ paddingLeft: `${depth * 16}px` }}
      >
        <svg
          className={`h-3.5 w-3.5 text-slate-400 dark:text-slate-500 transition-transform shrink-0 ${open ? "rotate-90" : ""}`}
          viewBox="0 0 20 20" fill="currentColor"
        >
          <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
        </svg>
        <svg className="h-3.5 w-3.5 text-blue-400 dark:text-blue-400 shrink-0" viewBox="0 0 20 20" fill="currentColor">
          <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
        </svg>
        <span className="text-xs font-mono font-medium text-slate-700 dark:text-slate-300 truncate">{name}</span>
      </button>

      {open && (
        <div>
          {Object.entries(node)
            .sort(([, a], [, b]) => {
              const aIsDir = a !== null && typeof a === "object";
              const bIsDir = b !== null && typeof b === "object";
              if (aIsDir && !bIsDir) return -1;
              if (!aIsDir && bIsDir) return 1;
              return 0;
            })
            .map(([childName, childNode]) => (
              <TreeNode key={childName} name={childName} node={childNode} depth={depth + 1} />
            ))}
        </div>
      )}
    </div>
  );
}

export default function FileTree({ files }: Props) {
  const tree = buildTree(files);
  const [globalOpen, setGlobalOpen] = useState<boolean | null>(null);

  // Reset globalOpen after one render cycle so per-node toggles work again
  function setAll(open: boolean) {
    setGlobalOpen(open);
    // Allow individual toggles after the forced state propagates
    setTimeout(() => setGlobalOpen(null), 50);
  }

  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-100 dark:border-slate-700">
        <span className="text-xs text-slate-500 dark:text-slate-400">{files.length} files</span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAll(true)}
            className="text-xs text-slate-500 dark:text-slate-400 hover:text-blue-700 dark:hover:text-blue-300 transition-colors"
          >
            Expand all
          </button>
          <span className="text-slate-300 dark:text-slate-600">·</span>
          <button
            onClick={() => setAll(false)}
            className="text-xs text-slate-500 dark:text-slate-400 hover:text-blue-700 dark:hover:text-blue-300 transition-colors"
          >
            Collapse all
          </button>
        </div>
      </div>

      <div className="p-3 overflow-auto max-h-[600px]">
        <TreeStateCtx.Provider value={{ globalOpen }}>
          {Object.entries(tree)
            .sort(([, a], [, b]) => {
              const aIsDir = a !== null && typeof a === "object";
              const bIsDir = b !== null && typeof b === "object";
              if (aIsDir && !bIsDir) return -1;
              if (!aIsDir && bIsDir) return 1;
              return 0;
            })
            .map(([name, node]) => (
              <TreeNode key={name} name={name} node={node} depth={0} />
            ))}
        </TreeStateCtx.Provider>
      </div>
    </div>
  );
}

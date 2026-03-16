import { useState, useMemo } from "react";
import { KnowledgeDocumentSummary } from "../api";

interface FileNode {
       name: string;
       path: string; // The full path
       isDirectory: boolean;
       children: Record<string, FileNode>;
       document?: KnowledgeDocumentSummary;
}

interface FileTreeProps {
       documents: KnowledgeDocumentSummary[];
       selectedPath: string;
       onSelect: (path: string) => void;
       searchQuery?: string;
}

export default function FileTree({ documents, selectedPath, onSelect, searchQuery = "" }: FileTreeProps) {
       const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set(["core"]));

       const toggleFolder = (path: string) => {
              setExpandedFolders(prev => {
                     const next = new Set(prev);
                     if (next.has(path)) {
                            next.delete(path);
                     } else {
                            next.add(path);
                     }
                     return next;
              });
       };

       const { tree, filteredPaths } = useMemo(() => {
              const root: FileNode = { name: "root", path: "", isDirectory: true, children: {} };
              const matchingPaths = new Set<string>();
              const lowerQuery = searchQuery.toLowerCase();

              // 1. Build the tree
              for (const doc of documents) {
                     if (lowerQuery && !(doc.path.toLowerCase().includes(lowerQuery) || doc.title.toLowerCase().includes(lowerQuery))) {
                            continue;
                     }

                     // Add all parent paths to matching paths if children match
                     if (lowerQuery) {
                            matchingPaths.add(doc.path);
                            let currentParent = doc.path;
                            while (currentParent.includes("/")) {
                                   currentParent = currentParent.substring(0, currentParent.lastIndexOf("/"));
                                   matchingPaths.add(currentParent);
                            }
                     }

                     const parts = doc.path.split("/");
                     let current = root;
                     let currentPath = "";

                     for (let i = 0; i < parts.length; i++) {
                            const part = parts[i];
                            const isFile = i === parts.length - 1;
                            currentPath = currentPath ? `${currentPath}/${part}` : part;

                            if (!current.children[part]) {
                                   current.children[part] = {
                                          name: part,
                                          path: currentPath,
                                          isDirectory: !isFile,
                                          children: {},
                                   };
                            }

                            if (isFile) {
                                   current.children[part].document = doc;
                            }

                            current = current.children[part];
                     }
              }

              return { tree: root, filteredPaths: matchingPaths };
       }, [documents, searchQuery]);

       const renderNode = (node: FileNode, level: number = 0) => {
              // If we're searching, only show nodes that are in the matching path set
              if (searchQuery && node.path && !filteredPaths.has(node.path)) {
                     return null;
              }

              if (node.isDirectory) {
                     // Force expand matching folders during search
                     const isExpanded = searchQuery ? true : expandedFolders.has(node.path);

                     // Sort: Folders first, then files. Alphabetically.
                     const children = Object.values(node.children).sort((a, b) => {
                            if (a.isDirectory !== b.isDirectory) {
                                   return a.isDirectory ? -1 : 1;
                            }
                            return a.name.localeCompare(b.name);
                     });

                     return (
                            <div key={node.path} className="w-full">
                                   <button
                                          onClick={() => toggleFolder(node.path)}
                                          className="flex w-full items-center gap-2 py-1.5 hover:bg-slate-800/50 rounded-md transition-colors text-left"
                                          style={{ paddingLeft: `${level * 16}px` }}
                                   >
                                          <span className="material-symbols-outlined text-[16px] text-slate-400 shrink-0">
                                                 {isExpanded ? "folder_open" : "folder"}
                                          </span>
                                          <span className="text-sm font-medium text-slate-300 truncate">{node.name}</span>
                                   </button>

                                   {isExpanded && (
                                          <div className="flex flex-col">
                                                 {children.map(child => renderNode(child, level + 1))}
                                          </div>
                                   )}
                            </div>
                     );
              }

              // File Node
              const isSelected = selectedPath === node.path;
              const doc = node.document;

              let icon = "draft";
              let iconColor = "text-slate-500";

              if (doc?.extension === ".md") { icon = "markdown"; iconColor = "text-sky-400"; }
              else if (doc?.extension === ".csv") { icon = "table_chart"; iconColor = "text-emerald-400"; }
              else if (doc?.extension === ".txt") { icon = "description"; iconColor = "text-slate-400"; }

              return (
                     <button
                            key={node.path}
                            onClick={() => onSelect(node.path)}
                            className={`flex w-full items-center gap-2 py-1.5 pr-2 rounded-md transition-colors text-left group ${isSelected ? "bg-primary/20 text-primary" : "hover:bg-slate-800/50 text-slate-400"
                                   }`}
                            style={{ paddingLeft: `${level * 16}px` }}
                     >
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                                   <span className={`material-symbols-outlined text-[16px] shrink-0 ${isSelected ? "text-primary" : iconColor}`}>
                                          {icon}
                                   </span>
                                   <span className={`text-sm truncate ${isSelected ? "font-semibold" : ""}`}>
                                          {doc?.title || node.name}
                                   </span>
                            </div>

                            {/* Badges / Labels */}
                            <div className="flex items-center gap-1.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                                   {doc?.is_core && (
                                          <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-amber-500">
                                                 core
                                          </span>
                                   )}
                                   {!doc?.is_indexable && !doc?.is_core && (
                                          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-slate-500">
                                                 omit
                                          </span>
                                   )}
                            </div>
                     </button>
              );
       };

       const rootChildren = Object.values(tree.children).sort((a, b) => {
              if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1;
              return a.name.localeCompare(b.name);
       });

       if (documents.length === 0) {
              return <div className="text-sm text-slate-500 p-4">No documents found.</div>;
       }

       return (
              <div className="flex flex-col gap-0.5 w-full">
                     {rootChildren.map(child => renderNode(child, 0))}
              </div>
       );
}

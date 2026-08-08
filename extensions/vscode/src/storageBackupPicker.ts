import * as vscode from "vscode";

import { formatStorageBytes, type StorageProject, type StorageTree } from "./storageBackupProtocol";

export async function chooseStorageTree(projects: readonly StorageProject[]): Promise<StorageTree | undefined> {
  const project = await vscode.window.showQuickPick(
    projects.map((item) => ({
      label: item.projectLabel,
      description: `${item.trees.length} task ${item.trees.length === 1 ? "tree" : "trees"}`,
      project: item,
    })),
    { title: "Back Up Task: Choose a Project", placeHolder: "Choose one project to back up a task from." },
  );
  if (!project) {
    return undefined;
  }
  const tree = await vscode.window.showQuickPick(
    project.project.trees.map((item) => ({
      label: item.title || item.rootTaskId,
      description: formatStorageBytes(item.totalBytes),
      detail: treeDetail(item),
      tree: item,
    })),
    {
      title: `Back Up Task: Choose a Task from ${project.project.projectLabel}`,
      placeHolder: `Search task trees in ${project.project.projectLabel}.`,
    },
  );
  return tree?.tree;
}

function treeDetail(tree: StorageTree): string {
  const flags = [
    tree.recoveryReady ? "" : "salvage only",
    tree.hasMissingRoot ? "root missing" : "",
    tree.hasRelationshipCycle ? "relationship cycle" : "",
    tree.duplicateFileCount ? `${tree.duplicateFileCount} duplicate files` : "",
  ].filter(Boolean);
  const composition = `${tree.physicalFileCount} files | root ${formatStorageBytes(tree.rootBytes)} | descendants ${formatStorageBytes(tree.descendantBytes)}`;
  return flags.length ? `${composition} | ${flags.join(", ")}` : composition;
}

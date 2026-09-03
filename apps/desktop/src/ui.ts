import {
  ArrowLeft,
  ArrowLeftRight,
  ArrowRight,
  ChartNoAxesCombined,
  ChevronRight,
  CircleAlert,
  CloudDownload,
  CloudOff,
  CloudUpload,
  Database,
  Download,
  Folder,
  FolderCog,
  FolderOpen,
  FolderPlus,
  FolderSearch,
  Folders,
  Gauge,
  HardDrive,
  ListChecks,
  RefreshCw,
  Save,
  ScanLine,
  ScanSearch,
  Search,
  Settings2,
  ShieldCheck,
  TriangleAlert,
  X,
  createIcons,
} from "lucide";

const icons = {
  ArrowLeft,
  ArrowLeftRight,
  ArrowRight,
  ChartNoAxesCombined,
  ChevronRight,
  CircleAlert,
  CloudDownload,
  CloudOff,
  CloudUpload,
  Database,
  Download,
  Folder,
  FolderCog,
  FolderOpen,
  FolderPlus,
  FolderSearch,
  Folders,
  Gauge,
  HardDrive,
  ListChecks,
  RefreshCw,
  Save,
  ScanLine,
  ScanSearch,
  Search,
  Settings2,
  ShieldCheck,
  TriangleAlert,
  X,
};

export function refreshIcons(root: Document | DocumentFragment | Element = document): void {
  createIcons({ icons, attrs: { "stroke-width": 1.8 }, nameAttr: "data-lucide", root });
}

export function setBusy(element: HTMLButtonElement, busy: boolean, label?: string): void {
  element.disabled = busy;
  element.toggleAttribute("aria-busy", busy);
  const text = element.querySelector<HTMLElement>("[data-button-label]");
  if (text && label) text.textContent = label;
}

export function showToast(message: string, kind: "info" | "success" | "error" = "info"): void {
  const region = document.querySelector<HTMLElement>("#toast-region");
  if (!region) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${kind}`;
  toast.setAttribute("role", kind === "error" ? "alert" : "status");
  toast.textContent = message;
  region.append(toast);
  window.setTimeout(() => toast.remove(), 5_000);
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function confirmDialog(options: {
  title: string;
  message: string;
  confirmLabel: string;
  destructive?: boolean;
}): Promise<boolean> {
  return new Promise((resolve) => {
    const template = document.querySelector<HTMLTemplateElement>("#confirm-dialog-template");
    if (!template) {
      resolve(false);
      return;
    }
    const dialog = template.content.firstElementChild?.cloneNode(true) as HTMLDialogElement;
    dialog.querySelector<HTMLElement>("[data-dialog-title]")!.textContent = options.title;
    dialog.querySelector<HTMLElement>("[data-dialog-message]")!.textContent = options.message;
    const confirm = dialog.querySelector<HTMLButtonElement>("[data-dialog-confirm]")!;
    confirm.textContent = options.confirmLabel;
    if (options.destructive) confirm.classList.add("button-danger");
    const close = (value: boolean): void => {
      dialog.close();
      dialog.remove();
      resolve(value);
    };
    dialog.querySelector<HTMLButtonElement>("[data-dialog-cancel]")!.addEventListener("click", () => close(false));
    confirm.addEventListener("click", () => close(true));
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      close(false);
    });
    document.body.append(dialog);
    dialog.showModal();
  });
}

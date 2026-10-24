"""Windows one-click recovery assistant; never changes the active installation."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.backups import BackupError
from utils.recovery import recover_backup_to_new_installation


def run() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError:
        print("Windows file chooser is unavailable. Install Python with Tcl/Tk support.")
        return 1

    root = tk.Tk()
    root.withdraw()
    try:
        selected = filedialog.askopenfilename(
            parent=root,
            title="Choose your Jobs-Finder backup ZIP",
            filetypes=[("Jobs-Finder ZIP backup", "*.zip")],
        )
        if not selected:
            return 0
        confirmed = messagebox.askyesno(
            "Restore without deleting existing work",
            "Jobs-Finder will verify this backup and create a NEW recovered "
            "copy beside your current project.\n\n"
            "Your existing program, database, saved CVs, and applications will "
            "NOT be overwritten.\n\n"
            "Continue?",
            parent=root,
        )
        if not confirmed:
            return 0
        try:
            result = recover_backup_to_new_installation(selected)
        except (BackupError, OSError) as exc:
            messagebox.showerror(
                "Backup could not be recovered",
                f"{exc}\n\nYour original Jobs-Finder files are unchanged.",
                parent=root,
            )
            return 1
        folder = Path(str(result["recovered_folder"]))
        messagebox.showinfo(
            "Recovered copy created successfully",
            f"Recovered {result['vacancies']} saved jobs and "
            f"{result['submitted_applications']} submitted applications.\n\n"
            f"New folder:\n{folder}\n\n"
            "Open the file run_jobs_finder.bat inside that folder to use the "
            "recovered copy. Your original Jobs-Finder was NOT modified.\n\n"
            "The new copy may need to install Python dependencies when first launched.",
            parent=root,
        )
        return 0
    finally:
        root.destroy()


if __name__ == "__main__":
    raise SystemExit(run())

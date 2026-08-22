"""Offline Tk review tool with autosave and resume."""

from __future__ import annotations

import argparse
import csv
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageOps, ImageTk

DECISIONS = {
    "a": "accept_add",
    "p": "accept_replace_gt",
    "e": "accept_eval_label",
    "d": "reject",
    "u": "uncertain",
}


def _read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def _write_rows(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class Reviewer:
    def __init__(self, root: tk.Tk, review_root: Path, decisions_path: Path) -> None:
        self.root = root
        self.review_root = review_root
        self.decisions_path = decisions_path
        template = review_root / "company_decisions_template.csv"
        source = decisions_path if decisions_path.exists() else template
        self.rows, self.fields = _read_rows(source)
        if not self.rows:
            raise ValueError("Review queue is empty")
        for field in ("reviewer_decision", "reviewer_comment"):
            if field not in self.fields:
                self.fields.append(field)
            for row in self.rows:
                row.setdefault(field, "")
        self.index = next((index for index, row in enumerate(self.rows) if not row["reviewer_decision"]), 0)
        self.photo = None

        root.title("GT/AUTO Company Review")
        root.geometry("1500x940")
        self.header = tk.Label(root, anchor="w", justify="left", font=("Segoe UI", 11))
        self.header.pack(fill="x", padx=10, pady=6)
        self.canvas = tk.Label(root, bg="#252525")
        self.canvas.pack(fill="both", expand=True, padx=10)
        self.comment = tk.Entry(root, font=("Segoe UI", 11))
        self.comment.pack(fill="x", padx=10, pady=6)
        controls = tk.Frame(root)
        controls.pack(fill="x", padx=10, pady=6)
        for text, key in [
            ("A Accept Add", "a"),
            ("P Replace GT", "p"),
            ("E Accept Eval", "e"),
            ("D Reject", "d"),
            ("U Uncertain", "u"),
        ]:
            tk.Button(controls, text=text, command=lambda value=key: self.decide(value)).pack(side="left", padx=4)
        tk.Button(controls, text="Previous", command=self.previous).pack(side="right", padx=4)
        tk.Button(controls, text="Next", command=self.next).pack(side="right", padx=4)

        for key in DECISIONS:
            root.bind(key, lambda event, value=key: self.decide(value))
        root.bind("<Left>", lambda event: self.previous())
        root.bind("<Right>", lambda event: self.next())
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.show()

    def save(self) -> None:
        _write_rows(self.decisions_path, self.rows, self.fields)

    def show(self) -> None:
        row = self.rows[self.index]
        completed = sum(bool(item["reviewer_decision"]) for item in self.rows)
        self.header.config(
            text=(
                f"{self.index + 1}/{len(self.rows)} | completed {completed} | "
                f"{row['candidate_id']} | {row['class_name']} | {row['case_code']} | "
                f"conf={row['conf']} | recommendation={row['recommended_action']} | "
                f"decision={row['reviewer_decision'] or 'PENDING'}"
            )
        )
        self.comment.delete(0, tk.END)
        self.comment.insert(0, row.get("reviewer_comment", ""))
        visual = self.review_root / row["visual_file"]
        try:
            image = ImageOps.exif_transpose(Image.open(visual)).convert("RGB")
            max_width = max(300, self.root.winfo_width() - 40)
            max_height = max(300, self.root.winfo_height() - 160)
            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(image)
            self.canvas.config(image=self.photo, text="")
        except Exception as error:
            self.canvas.config(image="", text=f"Cannot open {visual}\n{error}", fg="white")

    def decide(self, key: str) -> None:
        row = self.rows[self.index]
        decision = DECISIONS[key]
        allowed = {
            "accept_add_or_reject": {"accept_add", "reject", "uncertain"},
            "add_or_reject": {"accept_add", "reject", "uncertain"},
            "replace_or_reject": {"accept_replace_gt", "reject", "uncertain"},
            "accept_eval_or_reject": {"accept_eval_label", "reject", "uncertain"},
        }.get(row["recommended_action"], {"reject", "uncertain"})
        if decision not in allowed:
            messagebox.showwarning("Decision not allowed", f"{decision} is invalid for {row['recommended_action']}")
            return
        row["reviewer_decision"] = decision
        row["reviewer_comment"] = self.comment.get().strip()
        self.save()
        self.next()

    def previous(self) -> None:
        self.index = max(0, self.index - 1)
        self.show()

    def next(self) -> None:
        self.index = min(len(self.rows) - 1, self.index + 1)
        self.show()

    def close(self) -> None:
        self.rows[self.index]["reviewer_comment"] = self.comment.get().strip()
        self.save()
        self.root.destroy()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_root", type=Path)
    parser.add_argument("--decisions", type=Path)
    args = parser.parse_args(argv)
    review_root = args.review_root.expanduser().resolve()
    decisions = args.decisions.expanduser().resolve() if args.decisions else review_root / "company_decisions.csv"
    root = tk.Tk()
    Reviewer(root, review_root, decisions)
    root.mainloop()


if __name__ == "__main__":
    main()

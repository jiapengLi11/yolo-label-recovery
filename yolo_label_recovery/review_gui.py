"""Image-grouped offline reviewer with journaled autosave and CSV export."""

from __future__ import annotations

import argparse
import csv
import json
import locale
import os
import tkinter as tk
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, timezone
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

ALLOWED = {
    "accept_add_or_reject": {"accept_add", "reject", "uncertain"},
    "add_or_reject": {"accept_add", "reject", "uncertain"},
    "replace_or_reject": {"accept_replace_gt", "reject", "uncertain"},
    "accept_eval_or_reject": {"accept_eval_label", "reject", "uncertain"},
}

SPLIT_PRIORITY = {"train": 0, "val": 1, "test": 2}
CASE_PRIORITY = {
    "TRAIN_MISSING_HIGH": 0,
    "TRAIN_MISSING_MEDIUM": 1,
    "GT_SAME_AMBIGUOUS": 2,
    "GT_CROSS_CLASS_CONFLICT": 3,
    "EVAL_MISSING_HIGH": 4,
    "EVAL_MISSING_MEDIUM": 5,
}
CLASS_PRIORITY = {"tractor": 0, "smoking": 1, "slipper": 2, "helmet": 3, "vest": 4, "person": 5}

REQUIRED_FIELDS = {
    "candidate_id",
    "split",
    "image",
    "image_name",
    "class_name",
    "conf",
    "case_code",
    "recommended_action",
    "visual_file",
}

TEXT = {
    "en": {
        "title": "GT/AUTO Grouped Review",
        "candidate_list": "Candidates in current image",
        "legend": "Red=AUTO candidate  other colors=GT  thick gold=closest same-class GT",
        "comment": "Comment:",
        "accept_add": "Accept add",
        "accept_replace_gt": "Replace GT",
        "accept_eval_label": "Accept eval",
        "reject": "Reject",
        "uncertain": "Uncertain",
        "save": "Save results",
        "next_pending": "Next pending image",
        "next_image": "Next image",
        "previous_image": "Previous image",
        "next_box": "Next box",
        "previous_box": "Previous box",
        "pending": "PENDING",
        "image": "image",
        "candidate": "candidate",
        "group_completed": "group completed",
        "total_completed": "total completed",
        "split": "split",
        "class": "class",
        "confidence": "confidence",
        "decision": "decision",
        "save_complete": "Save complete",
        "saved_to": "Review results saved to:",
        "review_complete": "Review complete",
        "all_complete": "Every candidate has an explicit decision.",
        "decision_not_allowed": "Decision not allowed",
        "invalid_decision": "{decision} is invalid for {recommendation}",
        "cannot_open": "Cannot open image:",
        "journal_replayed": "recovered journal events",
        "case.TRAIN_MISSING_HIGH": "high-confidence train omission",
        "case.TRAIN_MISSING_MEDIUM": "train omission for review",
        "case.GT_SAME_AMBIGUOUS": "same-target extent conflict",
        "case.GT_CROSS_CLASS_CONFLICT": "cross-class box conflict",
        "case.EVAL_MISSING_HIGH": "high-confidence eval omission",
        "case.EVAL_MISSING_MEDIUM": "eval omission for review",
    },
    "zh-CN": {
        "title": "GT/AUTO 按图片聚合审核",
        "candidate_list": "当前图片的候选框",
        "legend": "红框=AUTO候选  其他颜色=原GT  金色粗框=最接近同类GT",
        "comment": "审核备注：",
        "accept_add": "确认新增",
        "accept_replace_gt": "替换原标注",
        "accept_eval_label": "确认评测集新增",
        "reject": "拒绝候选",
        "uncertain": "暂不确定",
        "save": "保存审核结果",
        "next_pending": "下一张未审核",
        "next_image": "下一张图片",
        "previous_image": "上一张图片",
        "next_box": "下一个框",
        "previous_box": "上一个框",
        "pending": "待审核",
        "image": "图片",
        "candidate": "当前图候选",
        "group_completed": "本图完成",
        "total_completed": "总进度",
        "split": "数据划分",
        "class": "类别",
        "confidence": "置信度",
        "decision": "决策",
        "save_complete": "保存完成",
        "saved_to": "审核结果已保存至：",
        "review_complete": "审核完成",
        "all_complete": "所有候选都已有明确决策。",
        "decision_not_allowed": "当前操作不可用",
        "invalid_decision": "决策 {decision} 不适用于 {recommendation}",
        "cannot_open": "无法打开图片：",
        "journal_replayed": "已恢复日志记录",
        "case.TRAIN_MISSING_HIGH": "训练集高置信疑似漏标",
        "case.TRAIN_MISSING_MEDIUM": "训练集待复核疑似漏标",
        "case.GT_SAME_AMBIGUOUS": "同目标框尺度冲突",
        "case.GT_CROSS_CLASS_CONFLICT": "跨类别框冲突",
        "case.EVAL_MISSING_HIGH": "评测集高置信疑似漏标",
        "case.EVAL_MISSING_MEDIUM": "评测集待复核疑似漏标",
    },
}


def detect_language(value: str) -> str:
    if value != "auto":
        return value
    language = (locale.getlocale()[0] or os.getenv("LANG", "")).lower()
    return "zh-CN" if language.startswith("zh") else "en"


def read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if not rows:
        raise ValueError(f"Review queue is empty: {path}")
    missing = sorted(REQUIRED_FIELDS.difference(fields))
    if missing:
        raise ValueError(f"Review queue is missing required columns: {', '.join(missing)}")
    return rows, fields


def atomic_write_rows(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def group_rows(rows: list[dict[str, str]]) -> list[list[int]]:
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[(row["split"], row["image"])].append(index)
    groups = list(grouped.values())

    def priority(indexes: list[int]) -> tuple[int, int, int, str]:
        items = [rows[index] for index in indexes]
        return (
            SPLIT_PRIORITY.get(items[0]["split"], 99),
            min(CASE_PRIORITY.get(item["case_code"], 99) for item in items),
            min(CLASS_PRIORITY.get(item["class_name"], 99) for item in items),
            items[0]["image_name"],
        )

    groups.sort(key=priority)
    for indexes in groups:
        indexes.sort(key=lambda index: (rows[index]["class_name"], rows[index]["candidate_id"]))
    return groups


def replay_journal(path: Path, rows_by_id: dict[str, dict[str, str]]) -> int:
    if not path.exists():
        return 0
    replayed = 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            row = rows_by_id.get(event.get("candidate_id", ""))
            if row is None:
                continue
            row["reviewer_decision"] = event.get("reviewer_decision", "")
            row["reviewer_comment"] = event.get("reviewer_comment", "")
            replayed += 1
    return replayed


def _confidence(row: dict[str, str]) -> float:
    try:
        return float(row["conf"])
    except (TypeError, ValueError):
        return 0.0


class GroupedReviewer:
    def __init__(
        self,
        root: tk.Tk,
        review_root: Path,
        decisions_path: Path,
        *,
        language: str = "auto",
        checkpoint_interval: int = 500,
    ) -> None:
        self.root = root
        self.review_root = review_root
        self.decisions_path = decisions_path
        self.language = detect_language(language)
        self.labels = TEXT[self.language]
        self.checkpoint_interval = max(1, checkpoint_interval)
        self.journal_path = review_root / "company_decisions_progress.jsonl"
        template = review_root / "company_decisions_template.csv"
        source = decisions_path if decisions_path.exists() else template
        self.rows, self.fields = read_rows(source)
        for field in ("reviewer_decision", "reviewer_comment"):
            if field not in self.fields:
                self.fields.append(field)
            for row in self.rows:
                row.setdefault(field, "")
        self.replayed_events = replay_journal(self.journal_path, {row["candidate_id"]: row for row in self.rows})
        self.groups = group_rows(self.rows)
        self.group_index = self.first_pending_group()
        self.member_index = self.first_pending_member(self.group_index)
        self.photo: ImageTk.PhotoImage | None = None
        self.source_image: Image.Image | None = None
        self.resize_job: str | None = None
        self.decisions_since_export = 0
        self.completed_count = sum(bool(row["reviewer_decision"]) for row in self.rows)

        root.title(self.labels["title"])
        root.geometry("1500x900")
        root.minsize(1050, 680)
        with suppress(tk.TclError):
            root.state("zoomed")
        font = "Microsoft YaHei UI" if self.language == "zh-CN" else "Segoe UI"
        self.header = tk.Label(root, anchor="w", justify="left", font=(font, 11, "bold"))
        self.header.pack(fill="x", padx=10, pady=6)

        body = tk.Frame(root)
        body.pack(fill="both", expand=True, padx=10)
        sidebar = tk.Frame(body, width=410)
        sidebar.pack(side="left", fill="y", padx=(0, 8))
        tk.Label(sidebar, text=self.labels["candidate_list"], anchor="w", font=(font, 10, "bold")).pack(fill="x")
        self.members = tk.Listbox(sidebar, width=56, font=("Consolas", 9), exportselection=False)
        self.members.pack(fill="both", expand=True)
        self.members.bind("<<ListboxSelect>>", self.select_member)
        tk.Label(
            sidebar,
            text=self.labels["legend"],
            anchor="w",
            justify="left",
            wraplength=400,
            fg="#555555",
            font=(font, 9),
        ).pack(fill="x", pady=(6, 0))

        self.canvas = tk.Label(body, bg="#252525")
        self.canvas.pack(side="right", fill="both", expand=True)
        self.canvas.bind("<Configure>", self.schedule_render)

        comment_frame = tk.Frame(root)
        comment_frame.pack(fill="x", padx=10, pady=6)
        tk.Label(comment_frame, text=self.labels["comment"], font=(font, 10)).pack(side="left")
        self.comment = tk.Entry(comment_frame, font=(font, 11))
        self.comment.pack(side="left", fill="x", expand=True)

        controls = tk.Frame(root)
        controls.pack(fill="x", padx=10, pady=6)
        self.decision_buttons: dict[str, tk.Button] = {}
        for key in DECISIONS:
            decision = DECISIONS[key]
            button = tk.Button(
                controls,
                text=f"{key.upper()} {self.labels[decision]}",
                font=(font, 10),
                command=lambda value=key: self.decide(value),
            )
            button.pack(side="left", padx=4)
            self.decision_buttons[decision] = button
        tk.Button(controls, text=self.labels["save"], command=self.export).pack(side="left", padx=14)
        for text_key, command in [
            ("next_pending", self.next_pending_group),
            ("next_image", lambda: self.move_group(1)),
            ("previous_image", lambda: self.move_group(-1)),
            ("next_box", lambda: self.move_member(1)),
            ("previous_box", lambda: self.move_member(-1)),
        ]:
            tk.Button(controls, text=self.labels[text_key], command=command).pack(side="right", padx=4)

        for key in DECISIONS:
            root.bind(key, lambda _event, value=key: self.decide(value))
        root.bind("<Left>", lambda _event: self.move_member(-1))
        root.bind("<Right>", lambda _event: self.move_member(1))
        root.bind("<Up>", lambda _event: self.move_group(-1))
        root.bind("<Down>", lambda _event: self.move_group(1))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(120, self.show_group)

    def first_pending_group(self) -> int:
        for group_index, indexes in enumerate(self.groups):
            if any(not self.rows[index]["reviewer_decision"] for index in indexes):
                return group_index
        return 0

    def first_pending_member(self, group_index: int) -> int:
        for member_index, row_index in enumerate(self.groups[group_index]):
            if not self.rows[row_index]["reviewer_decision"]:
                return member_index
        return 0

    def current_row(self) -> dict[str, str]:
        return self.rows[self.groups[self.group_index][self.member_index]]

    def append_event(self, row: dict[str, str]) -> None:
        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "candidate_id": row["candidate_id"],
            "reviewer_decision": row["reviewer_decision"],
            "reviewer_comment": row["reviewer_comment"],
        }
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def export(self, *, notify_user: bool = True) -> None:
        atomic_write_rows(self.decisions_path, self.rows, self.fields)
        self.decisions_since_export = 0
        if notify_user:
            messagebox.showinfo(self.labels["save_complete"], f"{self.labels['saved_to']}\n{self.decisions_path}")

    def show_group(self) -> None:
        indexes = self.groups[self.group_index]
        self.members.delete(0, tk.END)
        for row_index in indexes:
            row = self.rows[row_index]
            decision = row["reviewer_decision"] or self.labels["pending"]
            self.members.insert(
                tk.END,
                f"{decision:17} {row['class_name']:8} {_confidence(row):.3f} {row['case_code']} {row['candidate_id']}",
            )
        self.members.selection_set(self.member_index)
        self.members.see(self.member_index)
        self.show_member()

    def show_member(self) -> None:
        row = self.current_row()
        group = self.groups[self.group_index]
        group_completed = sum(bool(self.rows[index]["reviewer_decision"]) for index in group)
        case_label = self.labels.get(f"case.{row['case_code']}", row["case_code"])
        journal_note = f" | {self.labels['journal_replayed']} {self.replayed_events}" if self.replayed_events else ""
        self.header.config(
            text=(
                f"{self.labels['image']} {self.group_index + 1}/{len(self.groups)} | "
                f"{self.labels['candidate']} {self.member_index + 1}/{len(group)} | "
                f"{self.labels['group_completed']} {group_completed}/{len(group)} | "
                f"{self.labels['total_completed']} {self.completed_count}/{len(self.rows)} | "
                f"{self.labels['split']} {row['split']}{journal_note}\n"
                f"{row['image_name']} | {row['candidate_id']} | {self.labels['class']} {row['class_name']} | "
                f"{case_label} | {self.labels['confidence']} {_confidence(row):.3f} | "
                f"{self.labels['decision']} {row['reviewer_decision'] or self.labels['pending']}"
            )
        )
        self.comment.delete(0, tk.END)
        self.comment.insert(0, row.get("reviewer_comment", ""))
        visual = self.review_root / row["visual_file"]
        try:
            self.source_image = ImageOps.exif_transpose(Image.open(visual)).convert("RGB")
            self.render_current_image()
        except Exception as error:
            self.source_image = None
            self.canvas.config(image="", text=f"{self.labels['cannot_open']} {visual}\n{error}", fg="white")
        self.update_decision_buttons(row)

    def schedule_render(self, _event: tk.Event) -> None:
        if self.resize_job is not None:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(100, self.render_current_image)

    def render_current_image(self) -> None:
        self.resize_job = None
        if self.source_image is None:
            return
        max_width = max(300, self.canvas.winfo_width() - 24)
        max_height = max(300, self.canvas.winfo_height() - 24)
        width, height = self.source_image.size
        scale = min(max_width / width, max_height / height, 2.0)
        rendered = self.source_image.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            Image.Resampling.LANCZOS,
        )
        self.photo = ImageTk.PhotoImage(rendered)
        self.canvas.config(image=self.photo, text="")

    def update_decision_buttons(self, row: dict[str, str]) -> None:
        allowed = ALLOWED.get(row["recommended_action"], {"reject", "uncertain"})
        for decision, button in self.decision_buttons.items():
            button.config(state=tk.NORMAL if decision in allowed else tk.DISABLED)

    def select_member(self, _event: tk.Event) -> None:
        selection = self.members.curselection()
        if selection:
            self.member_index = selection[0]
            self.show_member()

    def decide(self, key: str) -> None:
        row = self.current_row()
        decision = DECISIONS[key]
        allowed = ALLOWED.get(row["recommended_action"], {"reject", "uncertain"})
        if decision not in allowed:
            messagebox.showwarning(
                self.labels["decision_not_allowed"],
                self.labels["invalid_decision"].format(decision=decision, recommendation=row["recommended_action"]),
            )
            return
        was_pending = not row["reviewer_decision"]
        row["reviewer_decision"] = decision
        row["reviewer_comment"] = self.comment.get().strip()
        if was_pending:
            self.completed_count += 1
        self.append_event(row)
        self.decisions_since_export += 1
        if self.decisions_since_export >= self.checkpoint_interval:
            self.export(notify_user=False)
        self.advance_pending()

    def advance_pending(self) -> None:
        group = self.groups[self.group_index]
        for offset in range(1, len(group) + 1):
            candidate = (self.member_index + offset) % len(group)
            if not self.rows[group[candidate]]["reviewer_decision"]:
                self.member_index = candidate
                self.show_group()
                return
        for offset in range(1, len(self.groups) + 1):
            candidate_group = (self.group_index + offset) % len(self.groups)
            if any(not self.rows[index]["reviewer_decision"] for index in self.groups[candidate_group]):
                self.group_index = candidate_group
                self.member_index = self.first_pending_member(candidate_group)
                self.show_group()
                return
        self.export(notify_user=False)
        messagebox.showinfo(self.labels["review_complete"], self.labels["all_complete"])

    def move_member(self, direction: int) -> None:
        self.member_index = max(0, min(len(self.groups[self.group_index]) - 1, self.member_index + direction))
        self.show_group()

    def move_group(self, direction: int) -> None:
        self.group_index = max(0, min(len(self.groups) - 1, self.group_index + direction))
        self.member_index = self.first_pending_member(self.group_index)
        self.show_group()

    def next_pending_group(self) -> None:
        for offset in range(1, len(self.groups) + 1):
            candidate_group = (self.group_index + offset) % len(self.groups)
            if any(not self.rows[index]["reviewer_decision"] for index in self.groups[candidate_group]):
                self.group_index = candidate_group
                self.member_index = self.first_pending_member(candidate_group)
                self.show_group()
                return
        messagebox.showinfo(self.labels["review_complete"], self.labels["all_complete"])

    def close(self) -> None:
        self.current_row()["reviewer_comment"] = self.comment.get().strip()
        self.export(notify_user=False)
        self.root.destroy()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_root", nargs="?", type=Path)
    parser.add_argument("--review-root", dest="review_root_option", type=Path)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--lang", choices=["auto", "zh-CN", "en"], default="auto")
    parser.add_argument("--checkpoint-interval", type=int, default=500)
    args = parser.parse_args(argv)
    supplied_root = args.review_root_option or args.review_root
    if supplied_root is None:
        parser.error("review_root is required")
    review_root = Path(str(supplied_root).strip().rstrip('"')).expanduser().resolve()
    decisions = (
        Path(str(args.decisions).strip().rstrip('"')).expanduser().resolve()
        if args.decisions
        else review_root / "company_decisions.csv"
    )
    root = tk.Tk()
    GroupedReviewer(
        root,
        review_root,
        decisions,
        language=args.lang,
        checkpoint_interval=args.checkpoint_interval,
    )
    root.mainloop()


if __name__ == "__main__":
    main()

"""Generic click-to-sort support for ttk.Treeview column headings."""

import re
from tkinter import ttk
from typing import Callable, Dict, Optional, Tuple

_NUMERIC_CLEAN_PATTERN = re.compile(r"[^0-9.\-]")
ASCENDING_ARROW = " ▲"
DESCENDING_ARROW = " ▼"


def sort_key_for_cell(raw_text: str) -> Tuple[int, float, str]:
    """
    Build a sortable key for one table cell's displayed text.

    Numeric-looking values (plain numbers, percentages, or KB/MB sizes) sort
    by their numeric value; everything else sorts case-insensitively as text.
    Empty cells and placeholder dashes always sort last.

    :param raw_text: Displayed cell text
    :return: Comparable sort key
    """
    text = (raw_text or "").strip()
    if not text or text == "-":
        return (2, 0.0, "")

    cleaned = _NUMERIC_CLEAN_PATTERN.sub("", text)
    if cleaned not in ("", "-", "."):
        try:
            value = float(cleaned)
        except ValueError:
            value = None
        if value is not None:
            lowered = text.lower()
            if "kb" in lowered:
                value *= 1024.0
            elif "mb" in lowered:
                value *= 1024.0 * 1024.0
            return (0, value, "")

    return (1, 0.0, text.lower())


class TreeSorter:
    """Attaches click-to-sort behavior to a Treeview's column headings.

    Clicking a header cycles ascending -> descending -> unsorted. On the
    third click, ``on_clear`` (if given) is invoked so the owner can rebuild
    the tree in its natural, model-driven order.
    """

    def __init__(
        self,
        tree: ttk.Treeview,
        headings: Dict[str, str],
        on_clear: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        :param tree: Treeview whose headings should become sortable
        :param headings: Mapping of column id (``"#0"`` for the tree column, or a
            values-column id) to its base heading label
        :param on_clear: Called when sorting cycles back to unsorted
        """
        self._tree = tree
        self._headings = dict(headings)
        self._sort_column: Optional[str] = None
        self._sort_reverse = False
        self._on_clear = on_clear

        for column_id in self._headings:
            tree.heading(column_id, command=lambda c=column_id: self.sort_by(c))

    @property
    def is_sorted(self) -> bool:
        """True while a column sort is active (not the natural/unsorted order)."""
        return self._sort_column is not None

    def sort_by(self, column_id: str) -> None:
        """
        Sort the tree by the given column, cycling ascending/descending/unsorted.

        :param column_id: Column identifier, or ``"#0"`` for the tree's main column
        """
        if self._sort_column != column_id:
            self._sort_column = column_id
            self._sort_reverse = False
        elif not self._sort_reverse:
            self._sort_reverse = True
        else:
            self._sort_column = None
            self._sort_reverse = False
            self._update_headings()
            if self._on_clear is not None:
                self._on_clear()
            return

        self.reapply()

    def reapply(self) -> None:
        """Re-run the current sort; call after the tree's rows were rebuilt."""
        if self._sort_column is None:
            self._update_headings()
            return

        column_id = self._sort_column
        columns = list(self._tree["columns"])

        def cell_text(iid: str) -> str:
            if column_id == "#0":
                return self._tree.item(iid, "text")
            values = self._tree.item(iid, "values")
            index = columns.index(column_id)
            return str(values[index]) if index < len(values) else ""

        items = list(self._tree.get_children(""))
        items.sort(key=lambda iid: sort_key_for_cell(cell_text(iid)))
        if self._sort_reverse:
            items.reverse()

        for position, iid in enumerate(items):
            self._tree.move(iid, "", position)

        self._update_headings()

    def _update_headings(self) -> None:
        for column_id, base_text in self._headings.items():
            if column_id == self._sort_column:
                arrow = DESCENDING_ARROW if self._sort_reverse else ASCENDING_ARROW
                self._tree.heading(column_id, text=f"{base_text}{arrow}")
            else:
                self._tree.heading(column_id, text=base_text)

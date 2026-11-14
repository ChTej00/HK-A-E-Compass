"""Walk-forward (time-based) splits.

Train on everything before a cut-off date, test on the block right after it, then move the cut-off
forward and repeat. The model is always tested on data from *after* its training data, which is how it
would be used for real. Random k-fold would let it train on Tuesday to "predict" Monday.

    |---------- train ----------|-- test 1 --|
    |---------------- train -----------------|-- test 2 --|
    |----------------------- train ------------------------|-- test 3 --|
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Fold:
    number: int
    train_start: pd.Timestamp
    test_start: pd.Timestamp  # training uses only data strictly before this
    test_end: pd.Timestamp  # exclusive

    def label(self) -> str:
        last_day = self.test_end - pd.Timedelta(days=1)
        return f"{self.test_start:%d %b %Y} – {last_day:%d %b %Y}"


def walk_forward_folds(
    index: pd.DatetimeIndex, initial_train_days: int = 56, test_days: int = 14
) -> list[Fold]:
    """Expanding-window folds over `index`. Test blocks are whole days and never overlap."""
    start = index.min().normalize()
    end = index.max()
    folds = []
    test_start = start + pd.Timedelta(days=initial_train_days)
    while test_start + pd.Timedelta(days=test_days) <= end:
        test_end = test_start + pd.Timedelta(days=test_days)
        folds.append(Fold(len(folds) + 1, start, test_start, test_end))
        test_start = test_end
    return folds

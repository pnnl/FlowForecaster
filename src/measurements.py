"""
Measurement extraction from folded core graphs.

Space-time folding compacts a workflow instance into a core graph whose edge
attributes are matrices indexed [thread][iteration]: one cell per (parallel
pipeline, loop iteration) that the fold collapsed.  A 2-thread, 3-iteration
1000Genomes instance therefore records six measurements per edge.

The rule inference used to read cell [0][0] and throw the other five away, so
the base value handed to the predictor was one arbitrary sample rather than an
estimate.  This module consumes the whole matrix and derives, per edge:

  V       volume, mean over all folded cells
  S       access size, mean over all folded cells
  A       accesses, derived as V / S.  Sec. III-A of the paper treats accesses
          and access size as the *base* metrics and volume as *derived*, but
          traced instances record only volume and access size, so the
          relationship is inverted to recover A.
  V_sigma fan-in aggregate volume, Eq. 1: sum of V(e) over e in E^-(v).
          Folding stores the *mean* per-source volume alongside num_sources,
          so the aggregate is num_sources * V.
  cv      coefficient of variation across the folded cells.  This is the
          within-instance noise floor: it says how much the folded threads and
          iterations disagreed, independently of scale.
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from py_lib_flowforecaster import EdgeAttrType, EdgeType


def cells(value) -> List[float]:
    """
    Flatten a folded attribute into every measurement it holds.

    Folding leaves attributes in three shapes depending on how many threads and
    iterations were collapsed: a bare scalar, a flat list, or a
    [thread][iteration] matrix.  All three are handled.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(cells(item))
        return out
    try:
        return [float(value)]
    except (TypeError, ValueError):
        return []


def summarize(values: List[float]) -> dict:
    """Mean, spread and count of a set of folded measurements."""
    if not values:
        return {"mean": 0.0, "median": 0.0, "cv": 0.0, "n": 0}
    mean = float(np.mean(values))
    std = float(np.std(values))
    return {
        "mean": mean,
        "median": float(np.median(values)),
        "cv": (std / mean) if mean else 0.0,
        "n": len(values),
    }


@dataclass
class Observation:
    """Every measurement of one core-graph edge in one workflow instance."""

    scale: float
    edge_type: str
    volume: float
    access_size: float
    accesses: float
    num_sources: float
    num_destinations: float
    volume_aggregate: float
    accesses_aggregate: float
    folds: int = 0
    volume_cv: float = 0.0
    access_size_cv: float = 0.0
    source: str = ""
    volume_cells: List[float] = field(default_factory=list)

    @property
    def max_cv(self) -> float:
        return max(self.volume_cv, self.access_size_cv)


def edge_type_of(graph, src, dst, edge_data) -> str:
    """Recorded fan-in/fan-out/sequential label, or one inferred from degrees."""
    recorded = edge_data.get(EdgeAttrType.TYPE)
    if recorded:
        return getattr(recorded, "value", recorded)
    if graph.in_degree(dst) > 1:
        return EdgeType.FAN_IN
    if graph.out_degree(src) > 1:
        return EdgeType.FAN_OUT
    return EdgeType.SEQ


def observe_edge(graph, src, dst, edge_data, scale: float, source: str = "") -> Observation:
    """Reduce one folded edge to a single Observation at a known scale."""
    vol_cells = cells(edge_data.get(EdgeAttrType.DATA_VOL))
    acc_cells = cells(edge_data.get(EdgeAttrType.ACC_SIZE))
    src_cells = cells(edge_data.get(EdgeAttrType.NUM_SRC)) or [1.0]
    dst_cells = cells(edge_data.get(EdgeAttrType.NUM_DST)) or [1.0]

    vol = summarize(vol_cells)
    acc = summarize(acc_cells)
    volume = vol["mean"]
    access_size = acc["mean"]
    num_sources = summarize(src_cells)["mean"]
    num_destinations = summarize(dst_cells)["mean"]

    # A = V / S.  Volume is the derived metric in the paper, but instances only
    # record V and S, so accesses is recovered by inverting V = A * S.
    accesses = (volume / access_size) if access_size else 0.0

    # Eq. 1.  Folding stored the mean per-source volume, so the aggregate over
    # the in-edge set is num_sources * V.  For a sequential or fan-out edge
    # num_sources is 1 and the aggregate degenerates to V, as it should.
    volume_aggregate = volume * num_sources
    accesses_aggregate = (volume_aggregate / access_size) if access_size else 0.0

    return Observation(
        scale=float(scale),
        edge_type=edge_type_of(graph, src, dst, edge_data),
        volume=volume,
        access_size=access_size,
        accesses=accesses,
        num_sources=num_sources,
        num_destinations=num_destinations,
        volume_aggregate=volume_aggregate,
        accesses_aggregate=accesses_aggregate,
        folds=vol["n"],
        volume_cv=vol["cv"],
        access_size_cv=acc["cv"],
        source=source,
        volume_cells=vol_cells,
    )


_SCALE_PATTERNS = (
    re.compile(r"_(?:data|task)_scale[_-]([0-9]+(?:\.[0-9]+)?)", re.I),
    re.compile(r"[_.-]scale[_-]?([0-9]+(?:\.[0-9]+)?)", re.I),
    re.compile(r"[_.-]([0-9]+(?:\.[0-9]+)?)x(?:[_.-]|$)", re.I),
)


def scale_from_filename(path: str) -> Optional[float]:
    """
    Recover the scale coordinate a file was generated at, or None.

    Rules are fitted against the scale each instance was measured at, so the
    scale has to travel with the measurement.  Naming conventions understood:
    `..._data_scale_2.0.graphml`, `..._scale-4.graphml`, `...-8x.graphml`.
    A file with no scale marker is the unscaled base instance (1.0), which the
    caller decides, since only it knows the position in the series.
    """
    name = os.path.basename(path)
    for pattern in _SCALE_PATTERNS:
        found = pattern.search(name)
        if found:
            try:
                return float(found.group(1))
            except ValueError:
                continue
    return None


def resolve_scales(instance_files: List[str], explicit: Optional[List[float]] = None) -> List[float]:
    """
    Decide the scale coordinate of every instance in a series.

    Preference order: values given on the command line, then values parsed from
    the filenames, then the position in the series (1, 2, 3, ...) with a
    warning -- positional fallback is what silently turned the paper's 2x/4x/8x
    series into 1x/2x/3x and made every edge look exponential.
    """
    if explicit:
        if len(explicit) != len(instance_files):
            raise ValueError(
                f"got {len(explicit)} scales for {len(instance_files)} instances; "
                "they must correspond one-to-one"
            )
        return [float(s) for s in explicit]

    parsed = [scale_from_filename(f) for f in instance_files]
    if all(p is None for p in parsed):
        print("  WARNING: no scale markers in filenames; assuming the instances are "
              "1x, 2x, 3x, ... in the order given. Pass --data-scales/--task-scales "
              "if that is wrong -- fitting against the wrong scales misclassifies "
              "every edge.")
        return [float(i + 1) for i in range(len(instance_files))]

    # A file with no marker among files that have them is the unscaled base.
    scales = [1.0 if p is None else p for p in parsed]
    if len(set(scales)) != len(scales):
        print(f"  WARNING: duplicate scale coordinates {scales}; the series has "
              f"only {len(set(scales))} distinct point(s) and the fit is "
              "correspondingly under-determined.")
    return scales

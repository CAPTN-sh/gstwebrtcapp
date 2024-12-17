import argparse
from itertools import cycle
import sys
from typing import List
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from concurrent.futures import ThreadPoolExecutor
from parser import TRACER_ATTRIBUTES


def plot(
    df: pd.DataFrame,
    tracer: str,
    y: str,
    min_groups: int = 5,
    save_fig: bool = False,
    save_fig_name: str | None = None,
) -> None:
    if tracer not in TRACER_ATTRIBUTES:
        print(f"Tracer '{tracer}' not found.")
        return

    if y not in TRACER_ATTRIBUTES[tracer]:
        print(f"Attribute '{y}' not found in '{tracer}' tracer.")
        return

    plot_func = f"_plot_{tracer}"
    if hasattr(sys.modules[__name__], plot_func):
        getattr(sys.modules[__name__], plot_func)(df, y, min_groups, save_fig, save_fig_name)
    else:
        print(f"Plot function for '{tracer}' not found.")


def preprocess_data(df: pd.DataFrame, y_column: str) -> pd.Series:
    if "time" in y_column:
        return pd.to_timedelta(df[y_column]).dt.total_seconds()
    return pd.to_numeric(df[y_column], errors='coerce')


def select(
    df: pd.DataFrame,
    y_column: str,
    group_column: str,
    min_groups: int = 5,
    order_by: str = "desc",
) -> pd.DataFrame:
    min_groups = min(max(0, min_groups), df[group_column].nunique())
    if min_groups == 0:
        return df

    df_sorted = df.sort_values(y_column, ascending=False if order_by == "desc" else True)
    n_selected = 0
    selected_groups = []
    while n_selected < min_groups:
        for idx, row in df_sorted.iterrows():
            if row[group_column] not in selected_groups:
                selected_groups.append(row[group_column])
                n_selected += 1
            if n_selected == min_groups:
                break
    return df[df[group_column].isin(selected_groups)]


def _plot_interlatency(
    df: pd.DataFrame,
    y_column: str = "time",
    min_groups: int = 5,
    save_fig: bool = False,
    save_fig_name: str | None = None,
) -> None:
    df['from_to_pad'] = df['from_pad'].astype(str) + " -> " + df['to_pad'].astype(str)
    df[y_column] = preprocess_data(df, y_column).astype(float)
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')

    selected_df = select(df, y_column, 'from_to_pad', min_groups)

    plt.figure(figsize=(12, 8))
    cmap = plt.get_cmap('tab20', min_groups)
    line_styles = ['-', '--', '-.', ':', (0, (1, 1)), (0, (5, 1)), (0, (3, 5, 1, 5)), (0, (3, 1, 1, 1, 1, 1))]
    markers = ['o', 's', 'D', '^', 'v', '<', '>', '*', 'p', 'h', 'X', '+']

    line_cycle = cycle(line_styles)
    marker_cycle = cycle(markers)
    for i, (label, group) in enumerate(list(selected_df.groupby('from_to_pad'))):
        plt.plot(
            group['timestamp'],
            group[y_column],
            label=label,
            color=cmap(i),
            linestyle=next(line_cycle),
            marker=next(marker_cycle),
            markevery=10,
        )

    plt.xlabel("Timestamp")
    plt.ylabel(y_column + " (s)" if "time" in y_column else y_column)
    plt.title(f"Interlatency - {min_groups} groups")
    plt.xticks(rotation=45)
    plt.legend()
    plt.tight_layout()

    if save_fig:
        plt.savefig(save_fig_name or "interlatency.png")
    else:
        plt.show()


def _plot_proctime(
    df: pd.DataFrame,
    y_column: str = "time",
    min_groups: int = 5,
    save_fig: bool = False,
    save_fig_name: str | None = None,
) -> None:
    df[y_column] = preprocess_data(df, y_column).astype(float)
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')

    selected_df = select(df, y_column, 'element', min_groups)

    plt.figure(figsize=(12, 8))
    cmap = plt.get_cmap('tab20', min_groups)
    line_styles = ['-', '--', '-.', ':', (0, (1, 1)), (0, (5, 1)), (0, (3, 5, 1, 5)), (0, (3, 1, 1, 1, 1, 1))]
    markers = ['o', 's', 'D', '^', 'v', '<', '>', '*', 'p', 'h', 'X', '+']

    line_cycle = cycle(line_styles)
    marker_cycle = cycle(markers)
    for i, (label, group) in enumerate(list(selected_df.groupby('element'))):
        plt.plot(
            group['timestamp'],
            group[y_column],
            label=label,
            color=cmap(i),
            linestyle=next(line_cycle),
            marker=next(marker_cycle),
            markevery=10,
        )

    plt.xlabel("Timestamp")
    plt.ylabel(y_column + " (s)" if "time" in y_column else y_column)
    plt.title(f"Processing time - {min_groups} groups")
    plt.xticks(rotation=45)
    plt.legend()
    plt.tight_layout()

    if save_fig:
        plt.savefig(save_fig_name or "proctime.png")
    else:
        plt.show()


def _plot_framerate(
    df: pd.DataFrame,
    y_column: str = "time",
    min_groups: int = 5,
    save_fig: bool = False,
    save_fig_name: str | None = None,
) -> None:
    df[y_column] = preprocess_data(df, y_column).astype(float)
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')

    selected_df = select(df, y_column, 'element', min_groups)

    plt.figure(figsize=(12, 8))
    cmap = plt.get_cmap('tab20', min_groups)
    line_styles = ['-', '--', '-.', ':', (0, (1, 1)), (0, (5, 1)), (0, (3, 5, 1, 5)), (0, (3, 1, 1, 1, 1, 1))]
    markers = ['o', 's', 'D', '^', 'v', '<', '>', '*', 'p', 'h', 'X', '+']

    line_cycle = cycle(line_styles)
    marker_cycle = cycle(markers)
    for i, (label, group) in enumerate(list(selected_df.groupby('element'))):
        plt.plot(
            group['timestamp'],
            group[y_column],
            label=label,
            color=cmap(i),
            linestyle=next(line_cycle),
            marker=next(marker_cycle),
            markevery=10,
        )

    plt.xlabel("Timestamp")
    plt.ylabel(y_column + " (s)" if "time" in y_column else y_column)
    plt.title(f"Framerate - {min_groups} groups")
    plt.xticks(rotation=45)
    plt.legend()
    plt.tight_layout()

    if save_fig:
        plt.savefig(save_fig_name or "framerate.png")
    else:
        plt.show()


def _plot_scheduletime(
    df: pd.DataFrame,
    y_column: str = "time",
    min_groups: int = 5,
    save_fig: bool = False,
    save_fig_name: str | None = None,
) -> None:
    df[y_column] = preprocess_data(df, y_column).astype(float)
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')

    selected_df = select(df, y_column, 'pad', min_groups)

    plt.figure(figsize=(12, 8))
    cmap = plt.get_cmap('tab20', min_groups)
    line_styles = ['-', '--', '-.', ':', (0, (1, 1)), (0, (5, 1)), (0, (3, 5, 1, 5)), (0, (3, 1, 1, 1, 1, 1))]
    markers = ['o', 's', 'D', '^', 'v', '<', '>', '*', 'p', 'h', 'X', '+']

    line_cycle = cycle(line_styles)
    marker_cycle = cycle(markers)
    for i, (label, group) in enumerate(list(selected_df.groupby('pad'))):
        plt.plot(
            group['timestamp'],
            group[y_column],
            label=label,
            color=cmap(i),
            linestyle=next(line_cycle),
            marker=next(marker_cycle),
            markevery=10,
        )

    plt.xlabel("Timestamp")
    plt.ylabel(y_column + " (s)" if "time" in y_column else y_column)
    plt.title(f"Schedule time - {min_groups} groups")
    plt.xticks(rotation=45)
    plt.legend()
    plt.tight_layout()

    if save_fig:
        plt.savefig(save_fig_name or "scheduletime.png")
    else:
        plt.show()


def _plot_queuelevel(
    df: pd.DataFrame,
    y_column: str = "size_time",
    min_groups: int = 5,
    save_fig: bool = False,
    save_fig_name: str | None = None,
) -> None:
    df[y_column] = preprocess_data(df, y_column).astype(float)
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')

    selected_df = select(df, y_column, 'queue', min_groups)

    plt.figure(figsize=(12, 8))
    cmap = plt.get_cmap('tab20', min_groups)
    line_styles = ['-', '--', '-.', ':', (0, (1, 1)), (0, (5, 1)), (0, (3, 5, 1, 5)), (0, (3, 1, 1, 1, 1, 1))]
    markers = ['o', 's', 'D', '^', 'v', '<', '>', '*', 'p', 'h', 'X', '+']

    line_cycle = cycle(line_styles)
    marker_cycle = cycle(markers)
    for i, (label, group) in enumerate(list(selected_df.groupby('queue'))):
        plt.plot(
            group['timestamp'],
            group[y_column],
            label=label,
            color=cmap(i),
            linestyle=next(line_cycle),
            marker=next(marker_cycle),
            markevery=10,
        )

    plt.xlabel("Timestamp")
    plt.ylabel(y_column + " (s)" if "time" in y_column else y_column)
    plt.title(f"Queuelevel - {min_groups} groups")
    plt.xticks(rotation=45)
    plt.legend()
    plt.tight_layout()

    if save_fig:
        plt.savefig(save_fig_name or "queuelevel.png")
    else:
        plt.show()


def load_csvs(df_paths: List[str]) -> List[pd.DataFrame]:
    with ThreadPoolExecutor() as executor:
        return list(executor.map(pd.read_csv, df_paths))


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    # fmt: off
    argparser.add_argument("-f, --files", dest='files', type=str, required=True, help="parsed csv files with tracers output comma-separated")
    argparser.add_argument("-t, --tracers", dest='tracers', type=str, required=True, help="tracer names comma-separated")
    argparser.add_argument("-v, --values", dest='values', type=str, required=True, help="y-axis values to plot comma-separated")
    argparser.add_argument("-m", "--min-groups", dest='min_groups', type=int, default=5, help="minimum number of groups")
    argparser.add_argument("--same-tracer", dest='same_tracer', action='store_true', help="use the same tracer for all values")
    argparser.add_argument("--save-fig", dest='save_fig', action='store_true', help="save the figure")
    # fmt: on
    args = argparser.parse_args()

    df_paths = args.files.split(",")
    tracers = args.tracers.split(",")
    values = args.values.split(",")

    dfs = load_csvs(df_paths)

    if not args.same_tracer:
        for df, tracer, value in zip(dfs, tracers, values):
            plot(df, tracer, value, args.min_groups, args.save_fig)
    else:
        assert len(tracers) == 1 and len(dfs) == 1, "Same tracer option requires only one tracer and one csv file"
        for value in values:
            plot(dfs[0], tracers[0], value, args.min_groups, args.save_fig, f"{tracers[0]}_{value}.png")

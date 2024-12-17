import argparse
from concurrent.futures import ThreadPoolExecutor
import os
import re
import pandas as pd

GST_TYPES = ["string", "uint"]

TRACER_ATTRIBUTES = {
    "interlatency": ["from_pad", "to_pad", "time"],
    "proctime": ["element", "time"],
    "framerate": ["element", "time"],
    "scheduletime": ["pad", "time"],
    "queuelevel": [
        "queue",
        "size_bytes",
        "max_size_bytes",
        "size_buffers",
        "max_size_buffers",
        "size_time",
        "max_size_time",
    ],
}

ANSI_ESCAPE_REGEX = re.compile(r'\x1b\[[0-9;]*m')
TYPES_PATTERN = '|'.join(map(re.escape, GST_TYPES))
ATTRS_REGEX = re.compile(fr'(\w+)=\(({TYPES_PATTERN})\)(\S+)')
MAIN_REGEX = re.compile(
    r'(?P<timestamp>\d+:\d+:\d+\.\d+)\s+'
    r'\d+\s+0x[a-f0-9]+\s+TRACE\s+GST_TRACER\s+:0::\s+'
    r'(?P<tracer>\w+),\s+(?P<attributes>.+?)\s*;'
)


class TracerParser:
    def __init__(self) -> None:
        self.tracer_data = {tracer: [] for tracer in TRACER_ATTRIBUTES}

    def parse_line(self, line: str) -> None:
        line = ANSI_ESCAPE_REGEX.sub('', line)

        match = MAIN_REGEX.match(line)
        if not match:
            return

        timestamp = match.group("timestamp")
        tracer = match.group("tracer")
        attributes = match.group("attributes")

        attr_matches = ATTRS_REGEX.findall(attributes)
        attrs = {name: value for name, _, value in attr_matches}

        if tracer in self.tracer_data:
            self.tracer_data[tracer].append(
                [timestamp] + [TracerParser._trim_commas(attrs.get(attr, None)) for attr in TRACER_ATTRIBUTES[tracer]]
            )

    def parse_lines(self, lines) -> None:
        for line in lines:
            self.parse_line(line)

    def export_all(self, output_dir: str | None) -> None:
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            os.chdir(output_dir)

        for tracer, rows in self.tracer_data.items():
            df = pd.DataFrame(rows, columns=["timestamp"] + TRACER_ATTRIBUTES[tracer])
            df.to_csv(f"{tracer}.csv", index=False)

    @staticmethod
    def _trim_commas(line: str | None) -> str | None:
        return line.replace(",", "") if line else None


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    # fmt: off
    argparser.add_argument("-l", "--log-file", dest="log_file", type=str, required=True, help="path to the log file")
    argparser.add_argument("-o", "--output-dir", dest="output_dir", type=str, required=False, help="output directory")
    # fmt: on
    args = argparser.parse_args()

    parser = TracerParser()

    lines = []
    with open(args.log_file, "r") as log_file:
        lines = log_file.readlines()

    batch_size = 1000
    with ThreadPoolExecutor() as executor:
        for i in range(0, len(lines), batch_size):
            batch = lines[i : i + batch_size]
            executor.submit(parser.parse_lines, batch)

    parser.export_all()

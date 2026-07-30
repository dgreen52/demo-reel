"""CLI: python -m demoreel scenarios/my_scenario.py [-o output_dir]"""

import argparse

from .runner import record


def main() -> None:
    ap = argparse.ArgumentParser(prog="demoreel",
                                 description="Record a scripted app demo to mp4 + gif")
    ap.add_argument("scenario", help="path to a scenario .py file")
    ap.add_argument("-o", "--output", default="output", help="output directory")
    args = ap.parse_args()
    result = record(args.scenario, args.output)
    print(f"mp4: {result['mp4']}")
    print(f"gif: {result['gif']}")


if __name__ == "__main__":
    main()

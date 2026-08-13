"""SAGE CLI entry point."""

import argparse


def main():
    """Main entry point for the SAGE CLI."""
    parser = argparse.ArgumentParser(
        description="SAGE - A Python CLI tool",
        prog="sage"
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    
    args = parser.parse_args()
    print("SAGE CLI is ready!")


if __name__ == "__main__":
    main()
